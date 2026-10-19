#include "opendeck/runtime.hpp"

#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using namespace opendeck;

namespace {
void expect(bool condition, const char *message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

template <typename Error, typename Work> void expect_throw(Work work, const char *message) {
    try {
        work();
    } catch (const Error &) {
        return;
    }
    throw std::runtime_error(message);
}

class Queue final : public Input<Slot> {
public:
    explicit Queue(std::vector<Slot> slots) : slots_(std::move(slots)) {}

    std::optional<Slot> take() override {
        if (next_ == slots_.size()) {
            return std::nullopt;
        }
        return slots_[next_++];
    }

private:
    std::vector<Slot> slots_;
    std::size_t next_ = 0;
};

class Record final : public Action {
public:
    explicit Record(std::vector<std::string> &calls,
                    std::vector<Result> results = {{Status::done, "executed"}})
        : calls_(calls), results_(std::move(results)) {}
    Result run() override {
        calls_.push_back("run");
        return results_.at(next_++);
    }

private:
    std::vector<std::string> &calls_;
    std::vector<Result> results_;
    std::size_t next_ = 0;
};

void binding_keeps_configuration_without_running_actions() {
    std::vector<std::string> calls;
    auto action = std::make_shared<Record>(calls);
    const Slot first{"first"}, repeat{"repeat"}, missing{"missing"};
    std::map<Slot, std::shared_ptr<Action>> mapping{{first, action}, {repeat, action}};
    const Binding binding(mapping);
    mapping.clear();
    action.reset();

    expect(binding.select(first) != nullptr, "Binding must retain its actions");
    expect(binding.select(first) == binding.select(repeat), "Several inputs may reuse one Action");
    expect(binding.select(missing) == nullptr, "Unassigned input must remain distinguishable");
    expect(calls.empty(), "Binding construction and selection must not run actions");
}

void empty_input_does_not_report_or_execute() {
    Queue input({});
    const Binding binding({});
    bool reported = false;
    expect(drain(input, binding,
                 [&](const Slot &, const std::optional<Result> &) { reported = true; }) == 0,
           "An empty input must drain zero requests");
    expect(!reported, "An empty input must not produce a report");
}

void drain_executes_and_reports_each_request_in_order() {
    const Slot first{"first"}, repeat{"repeat"}, missing{"missing"};
    const std::vector<Result> results{
        {Status::done, "one"}, {Status::failed, "two"}, {Status::unknown, "three"}};
    std::vector<std::string> calls;
    const auto action = std::make_shared<Record>(calls, results);
    const Binding binding({{first, action}, {repeat, action}});
    Queue input({first, missing, repeat, first});
    std::vector<std::pair<Slot, std::optional<Result>>> reports;
    const auto report = [&](const Slot &slot, const std::optional<Result> &result) {
        calls.push_back("report:" + slot.name);
        reports.emplace_back(slot, result);
    };

    expect(drain(input, binding, report) == 4,
           "Drain must process all input occurrences, including unassigned ones");
    expect(reports == std::vector<std::pair<Slot, std::optional<Result>>>{{first, results[0]},
                                                                          {missing, std::nullopt},
                                                                          {repeat, results[1]},
                                                                          {first, results[2]}},
           "Each invocation must retain its own result and unassigned status");
    expect(calls == std::vector<std::string>{"run", "report:first", "report:missing", "run",
                                             "report:repeat", "run", "report:first"},
           "A request must finish and report before the next Action runs");
    expect(drain(input, binding, report) == 0 && reports.size() == 4,
           "Consumed requests must not execute again");
}

void input_failure_propagates_without_reporting_a_request() {
    class FailedInput final : public Input<Slot> {
    public:
        std::optional<Slot> take() override { throw InputError("disconnected"); }
    } input;
    bool reported = false;
    expect_throw<InputError>(
        [&] {
            drain(input, Binding({}),
                  [&](const Slot &, const std::optional<Result> &) { reported = true; });
        },
        "Input failure must reach the connection owner");
    expect(!reported, "Input failure must not be reported as a completed request");
}

void action_failure_stops_before_consuming_the_next_request() {
    class FailedAction final : public Action {
    public:
        Result run() override { throw std::runtime_error("action failure"); }
    };
    const Slot failed{"failed"}, following{"following"};
    Queue input({failed, following});
    const Binding binding({{failed, std::make_shared<FailedAction>()}});
    bool reported = false;
    expect_throw<std::runtime_error>(
        [&] {
            drain(input, binding,
                  [&](const Slot &, const std::optional<Result> &) { reported = true; });
        },
        "Unexpected Action exceptions must reach the caller");
    expect(!reported, "A throwing Action must not produce a fabricated result");
    expect(input.take() == following, "Failure must leave the next request unconsumed");
}

void report_failure_stops_before_consuming_the_next_request() {
    const Slot first{"first"}, following{"following"};
    Queue input({first, following});
    expect_throw<std::runtime_error>(
        [&] {
            drain(input, Binding({}), [](const Slot &, const std::optional<Result> &) {
                throw std::runtime_error("report failure");
            });
        },
        "Reporting exceptions must reach the caller");
    expect(input.take() == following, "Reporting failure must leave the next request unconsumed");
}
} // namespace

int main() {
    binding_keeps_configuration_without_running_actions();
    empty_input_does_not_report_or_execute();
    drain_executes_and_reports_each_request_in_order();
    input_failure_propagates_without_reporting_a_request();
    action_failure_stops_before_consuming_the_next_request();
    report_failure_stops_before_consuming_the_next_request();
}

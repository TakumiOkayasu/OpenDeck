#include "opendeck/panel.hpp"
#include "opendeck/recognition.hpp"
#include "opendeck/source.hpp"

#include <functional>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace opendeck;

void require(bool condition, const std::string &message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

template <typename Error, typename Function>
void throws(Function &&function, const std::string &message) {
    try {
        function();
    } catch (const Error &) {
        return;
    }
    throw std::runtime_error(message);
}

class Listener final : public Observer {
public:
    explicit Listener(std::function<void()> callback) : callback_(std::move(callback)) {}
    void on_change() override { callback_(); }

private:
    std::function<void()> callback_;
};

const Slot a{"a"};
const Slot b{"b"};
const Slot c{"c"};
const Slot ab{"ab"};
const Slot ac{"ac"};
const Slot abc{"abc"};

void recognition() {
    const State initial{{a, b, c}, {}};
    const std::vector<Chord> chords{{{a, b}, ab}, {{a, c}, ac}, {{a, b, c}, abc}};
    auto [following, emitted] = apply(initial, a, false, chords);
    require(emitted == std::vector<Slot>{abc}, "Largest chord must win");
    require(initial.held == std::set<Slot>{a, b, c}, "Recognition mutated its input");
    auto [next, suppressed] = apply(following, b, false, chords);
    auto [empty, last] = apply(next, c, false, chords);
    require(suppressed.empty() && last.empty() && empty.held.empty(),
            "Chord members must not also emit singles");
    const std::vector<Chord> tied{{{a, b}, ab}, {{a, c}, ac}};
    require(apply(initial, a, false, tied).second == std::vector<Slot>{ab},
            "Equal-size chords must follow declaration order");
    require(apply(initial, a, true, tied).second.empty(), "Duplicate press emitted");
    require(apply(State{}, a, false, tied).second.empty(), "Unheld release emitted");
    State single;
    for (int cycle = 0; cycle < 2; ++cycle) {
        single = apply(single, a, true, {}).first;
        auto result = apply(single, a, false, {});
        require(result.second == std::vector<Slot>{a}, "Single release did not repeat");
        single = std::move(result.first);
    }
    const State claimed{{b, c}, {b}};
    require(apply(claimed, c, false, {{{b, c}, ab}}).second == std::vector<Slot>{c},
            "Claimed member participated in another chord");
}

void adaptation_and_hold() {
    throws<std::invalid_argument>([] { apply(State{{a}, {b}}, a, true, {}); },
                                  "Invalid claimed state accepted");
    validate_adaptation({a, b}, {{{a, b}, ab}});
    throws<std::invalid_argument>([] { validate_adaptation({a, a}, {}); },
                                  "Duplicate base slots accepted");
    throws<std::invalid_argument>([] { validate_adaptation({a}, {{{a, b}, ab}}); },
                                  "Unavailable chord member accepted");
    throws<std::invalid_argument>([] { validate_adaptation({a}, {{{a}, ab}}); },
                                  "Single-member chord accepted");
    throws<std::invalid_argument>(
        [] { validate_adaptation({a, b, c}, {{{a, b}, ab}, {{ab, c}, abc}}); },
        "Nested chord unsupported by this recognizer was accepted");
    auto [held, active] = hold({a}, b, true, {{{a, b}, ab}});
    require(held == std::set<Slot>{a, b} && active == std::set<Slot>{a, b, ab},
            "Held chord must start when all members are held");
    require(hold(held, a, false, {{{a, b}, ab}}).second == std::set<Slot>{b},
            "Held chord must end on first release");
}

void fifo_and_observers() {
    Source<int> source(4);
    require(!source.take(), "Initial source must be empty");
    int calls = 0;
    auto observer = std::make_shared<Listener>([&] { ++calls; });
    source.add(observer);
    source.add(observer);
    source.start();
    source.publish(1);
    source.publish(1);
    source.publish(2);
    require(calls == 3, "Observer identity was not deduplicated");
    require(source.take() == 1 && source.take() == 1 && source.take() == 2 && !source.take(),
            "FIFO lost repeated occurrences or changed their order");
    source.remove(observer);
    source.remove(observer);
    source.publish(3);
    require(calls == 3, "Removed observer was notified");
    source.close();
    require(!source.take() && !source.publish(4), "Close must discard pending input");
}

void staging_and_failure() {
    Source<int> source(1);
    source.start();
    std::mutex outer;
    int calls = 0;
    auto observer = std::make_shared<Listener>([&] {
        require(outer.try_lock(), "Observer was called with caller lock held");
        outer.unlock();
        ++calls;
    });
    source.add(observer);
    Notifications pending;
    {
        std::lock_guard lock(outer);
        auto [accepted, observers] = source.enqueue(1);
        require(accepted && calls == 0, "Enqueue must not call observers");
        pending = std::move(observers);
    }
    source.close();
    Source<int>::notify(pending);
    require(calls == 1 && !source.take(), "Delayed notification delivered stale input");
    source.start();
    source.enqueue(1);
    auto [accepted, overflow] = source.enqueue(2);
    require(!accepted && calls == 1, "Overflow must be staged as a failure");
    Source<int>::notify(overflow);
    throws<InputError>([&] { source.take(); }, "Overflow failed to invalidate queue");
    source.close();
    throws<InputError>([&] { source.take(); }, "Close concealed source failure");
    source.start();
    require(!source.take(), "Reopen must clear old failures");
    source.record_failure("disconnected");
    throws<InputError>([&] { source.take(); }, "Transport failure was lost");
    throws<std::invalid_argument>([] { Source<int> invalid(0); }, "Zero capacity accepted");
}

void reentrant_source_notification() {
    Source<int> source;
    source.start();
    std::vector<int> received;
    std::shared_ptr<Listener> listener;
    listener = std::make_shared<Listener>([&] {
        auto item = source.take();
        require(item.has_value(), "Reentrant take did not receive pending input");
        received.push_back(*item);
        source.remove(listener);
    });
    source.add(listener);
    source.publish(7);
    source.publish(8);
    require(received == std::vector<int>{7} && source.take() == 8,
            "Observer removal or reentrant consumption failed");
}

void panel_history_and_chords() {
    Panel panel({a, b}, {{{a, b}, ab}}, 8);
    auto buttons = panel.buttons();
    throws<InputError>([&] { buttons.at(a)->read(); }, "Initial read must be unavailable");
    require(!buttons.at(a)->take(), "Initial history must be empty");
    panel.start();
    require(!buttons.at(a)->read() && !buttons.at(ab)->read(),
            "Start must establish released state");
    int calls = 0;
    auto listener = std::make_shared<Listener>([&] {
        require(buttons.at(a)->read(), "Observer saw incomplete panel state");
        ++calls;
    });
    buttons.at(a)->add(listener);
    auto [accepted, notifications] = panel.receive(a, true, 10.0);
    require(accepted && calls == 0, "Panel must not notify inside receive");
    Source<int>::notify(notifications);
    require(calls == 1, "Button observer not notified");
    require(panel.receive(a, true, 11.0).second.empty(), "Duplicate press was recorded");
    buttons.at(a)->remove(listener);
    panel.receive(b, true, 12.0);
    require(buttons.at(ab)->read(), "Held chord did not become active");
    panel.receive(a, false, 14.0);
    require(!buttons.at(ab)->read() && buttons.at(b)->read(),
            "First release must end only the chord and released member");
    panel.receive(b, false, 15.0);
    require(buttons.at(a)->take() == Change{true, 10.0} &&
                buttons.at(a)->take() == Change{false, 14.0} && !buttons.at(a)->take(),
            "Button history did not retain timestamps and order");
    require(buttons.at(ab)->take() == Change{true, 12.0} &&
                buttons.at(ab)->take() == Change{false, 14.0},
            "Chord history used incorrect transition times");
}

void late_button_notification() {
    Panel panel({a}, {}, 4);
    panel.start();
    panel.receive(a, true, 4.0);
    auto button = panel.buttons().at(a);
    int calls = 0;
    auto listener = std::make_shared<Listener>([&] {
        require(button->read(), "Late observer could not read current button state");
        require(button->take() == Change{true, 4.0}, "Late observer lost pending history");
        ++calls;
    });
    button->add(listener);
    require(calls == 1, "Late observer was not notified of pending input");
    button->remove(listener);
    panel.close();
    require(calls == 1, "Removed late observer was notified");
}

void panel_failure_and_reopen() {
    Panel panel({a, b}, {}, 1);
    auto buttons = panel.buttons();
    panel.start();
    panel.receive(a, true, 1.0);
    panel.receive(b, true, 2.0);
    auto [accepted, notifications] = panel.receive(a, false, 3.0);
    require(!accepted, "History overflow was accepted");
    for (const auto &[slot, button] : buttons) {
        throws<InputError>([&] { button->read(); }, "Failure did not invalidate all reads");
        throws<InputError>([&] { button->take(); }, "Failure did not clear all histories");
    }
    panel.start();
    require(!buttons.at(a)->read() && !buttons.at(a)->take(), "Reopen retained old state");
    panel.receive(a, true, 4.0);
    panel.close();
    throws<InputError>([&] { buttons.at(a)->read(); }, "Close left a readable pressed state");
    throws<InputError>([&] { buttons.at(a)->take(); }, "Close invented a release event");
    require(!panel.receive(a, false, 5.0).first, "Closed panel received input");
    throws<std::invalid_argument>([] { Panel invalid({a, b}, {{{a, b}, a}}, 2); },
                                  "Colliding button identities accepted");
}

} // namespace

int main() {
    try {
        recognition();
        adaptation_and_hold();
        fifo_and_observers();
        staging_and_failure();
        reentrant_source_notification();
        panel_history_and_chords();
        late_button_notification();
        panel_failure_and_reopen();
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
    return 0;
}

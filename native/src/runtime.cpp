#include "opendeck/runtime.hpp"

#include <utility>

namespace opendeck {

Binding::Binding(std::map<Slot, std::shared_ptr<Action>> actions) : actions_(std::move(actions)) {}

std::shared_ptr<Action> Binding::select(const Slot &slot) const {
    const auto found = actions_.find(slot);
    return found == actions_.end() ? nullptr : found->second;
}

std::size_t drain(Input<Slot> &input, const Binding &binding,
                  const std::function<void(const Slot &, const std::optional<Result> &)> &report) {
    std::size_t count = 0;
    while (const auto slot = input.take()) {
        const auto action = binding.select(*slot);
        std::optional<Result> result;
        if (action) {
            result = action->run();
        }
        report(*slot, result);
        ++count;
    }
    return count;
}

} // namespace opendeck

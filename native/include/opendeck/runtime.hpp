#pragma once

#include "opendeck/contracts.hpp"

#include <cstddef>
#include <functional>
#include <map>
#include <memory>
#include <optional>

namespace opendeck {

class Binding {
public:
    explicit Binding(std::map<Slot, std::shared_ptr<Action>> actions);
    std::shared_ptr<Action> select(const Slot &slot) const;

private:
    const std::map<Slot, std::shared_ptr<Action>> actions_;
};

std::size_t drain(Input<Slot> &input, const Binding &binding,
                  const std::function<void(const Slot &, const std::optional<Result> &)> &report);

} // namespace opendeck

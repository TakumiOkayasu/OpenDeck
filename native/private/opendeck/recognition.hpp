#pragma once

#include "opendeck/model.hpp"

#include <set>
#include <utility>
#include <vector>

namespace opendeck {

struct State {
    std::set<Slot> held;
    std::set<Slot> claimed;
    bool operator==(const State &) const = default;
};

void validate_state(const State &state);

void validate_adaptation(const std::vector<Slot> &slots, const std::vector<Chord> &chords);

std::pair<State, std::vector<Slot>> apply(const State &state, const Slot &slot, bool pressed,
                                          const std::vector<Chord> &chords = {});

std::pair<std::set<Slot>, std::set<Slot>> hold(const std::set<Slot> &held, const Slot &slot,
                                               bool pressed, const std::vector<Chord> &chords);

} // namespace opendeck

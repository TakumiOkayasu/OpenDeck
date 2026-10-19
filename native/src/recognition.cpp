#include "opendeck/recognition.hpp"

#include <algorithm>
#include <stdexcept>

namespace opendeck {
namespace {

bool contains_all(const std::set<Slot> &available, const std::set<Slot> &members) {
    return std::includes(available.begin(), available.end(), members.begin(), members.end());
}

} // namespace

void validate_state(const State &state) {
    if (!contains_all(state.held, state.claimed)) {
        throw std::invalid_argument("Claimed input slots must still be held");
    }
}

void validate_adaptation(const std::vector<Slot> &slots, const std::vector<Chord> &chords) {
    const std::set<Slot> available(slots.begin(), slots.end());
    if (available.size() != slots.size()) {
        throw std::invalid_argument("Each physical input must adapt to a distinct base slot");
    }
    for (const auto &chord : chords) {
        if (chord.members.size() < 2) {
            throw std::invalid_argument("A chord needs at least two input slots");
        }
        if (!contains_all(available, chord.members)) {
            throw std::invalid_argument("Chord members must all be adapted base slots");
        }
    }
}

std::pair<State, std::vector<Slot>> apply(const State &state, const Slot &slot, bool pressed,
                                          const std::vector<Chord> &chords) {
    validate_state(state);
    State following = state;
    if (pressed) {
        following.held.insert(slot);
        return {std::move(following), {}};
    }
    if (!following.held.erase(slot)) {
        return {std::move(following), {}};
    }
    if (following.claimed.erase(slot)) {
        return {std::move(following), {}};
    }
    auto available = state.held;
    for (const auto &claimed : state.claimed) {
        available.erase(claimed);
    }
    const Chord *selected = nullptr;
    for (const auto &chord : chords) {
        if (chord.members.contains(slot) && contains_all(available, chord.members) &&
            (selected == nullptr || chord.members.size() > selected->members.size())) {
            selected = &chord;
        }
    }
    if (selected == nullptr) {
        return {std::move(following), {slot}};
    }
    following.claimed.insert(selected->members.begin(), selected->members.end());
    following.claimed.erase(slot);
    return {std::move(following), {selected->slot}};
}

std::pair<std::set<Slot>, std::set<Slot>> hold(const std::set<Slot> &held, const Slot &slot,
                                               bool pressed, const std::vector<Chord> &chords) {
    auto following = held;
    if (pressed) {
        following.insert(slot);
    } else {
        following.erase(slot);
    }
    auto active = following;
    for (const auto &chord : chords) {
        if (contains_all(following, chord.members)) {
            active.insert(chord.slot);
        }
    }
    return {std::move(following), std::move(active)};
}

} // namespace opendeck

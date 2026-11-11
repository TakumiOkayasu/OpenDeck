#pragma once

#include <compare>
#include <set>
#include <string>

static_assert(__cplusplus >= 202302L, "OpenDeck requires C++23 or newer");

namespace opendeck {

struct Slot {
    std::string name;
    auto operator<=>(const Slot &) const = default;
};

struct Change {
    bool pressed;
    double at;
    bool operator==(const Change &) const = default;
};

struct TouchPoint {
    int x;
    int y;
    bool operator==(const TouchPoint &) const = default;
};

enum class Direction { left, right };

struct Swipe {
    Direction direction;
    bool operator==(const Swipe &) const = default;
};

struct Chord {
    std::set<Slot> members;
    Slot slot;
    bool operator==(const Chord &) const = default;
};

enum class Status { done, failed, unknown };

struct Result {
    Status status;
    std::string detail;
    bool operator==(const Result &) const = default;
};

} // namespace opendeck

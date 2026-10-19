#pragma once

#include "opendeck/contracts.hpp"
#include "opendeck/source.hpp"

#include <cstddef>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace opendeck {

class Panel {
public:
    Panel(std::vector<Slot> slots, std::vector<Chord> chords, std::size_t capacity = 256);
    ~Panel();
    Panel(const Panel &) = delete;
    Panel &operator=(const Panel &) = delete;

    void start();
    std::pair<bool, Notifications> receive(const Slot &slot, bool pressed, double at);
    std::map<Slot, std::shared_ptr<Button>> buttons() const;
    Notifications record_failure(std::string error);
    Notifications close(std::string error = "Button input closed");

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace opendeck

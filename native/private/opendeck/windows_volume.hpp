#pragma once

#include <cstdint>
#include <memory>
#include <utility>

namespace opendeck::windows {

std::pair<std::uint32_t, float> read_output_volume();
std::pair<std::uint32_t, bool> read_output_mute();
std::uint32_t set_output_volume(float level);
std::uint32_t set_output_mute(bool muted);

class VolumeWatch {
public:
    VolumeWatch();
    ~VolumeWatch();
    VolumeWatch(const VolumeWatch &) = delete;
    VolumeWatch &operator=(const VolumeWatch &) = delete;

    std::uint32_t start();
    std::pair<std::uint32_t, bool> wait();
    std::uint32_t refresh();
    void cancel();
    std::uint32_t close();

private:
    struct State;
    std::unique_ptr<State> state;
};

} // namespace opendeck::windows

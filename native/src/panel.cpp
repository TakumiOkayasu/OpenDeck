#include "opendeck/panel.hpp"

#include "opendeck/recognition.hpp"

#include <iterator>
#include <mutex>
#include <optional>
#include <set>
#include <stdexcept>

namespace opendeck {
namespace {

class ButtonState final : public Button {
public:
    ButtonState(std::shared_ptr<std::mutex> mutex, std::size_t capacity)
        : mutex_(std::move(mutex)), source_(capacity) {
        source_.start();
    }

    bool read() const override {
        std::lock_guard lock(*mutex_);
        if (error_) {
            throw InputError(*error_);
        }
        if (!pressed_) {
            throw InputError("Button input has not started");
        }
        return *pressed_;
    }

    std::optional<Change> take() override {
        std::lock_guard lock(*mutex_);
        return source_.take();
    }

    void add(std::shared_ptr<Observer> observer) override { source_.add(std::move(observer)); }
    void remove(std::shared_ptr<Observer> observer) override {
        source_.remove(std::move(observer));
    }

    void start() {
        source_.start();
        pressed_ = false;
        error_.reset();
    }

    std::pair<bool, Notifications> change(bool pressed, double at) {
        if (pressed_ == pressed) {
            return {true, {}};
        }
        pressed_ = pressed;
        return source_.enqueue(Change{pressed, at});
    }

    Notifications fail(const std::string &error) {
        if (error_) {
            return {};
        }
        pressed_.reset();
        error_ = error;
        return source_.record_failure(error);
    }

private:
    std::shared_ptr<std::mutex> mutex_;
    Source<Change> source_;
    std::optional<bool> pressed_;
    std::optional<std::string> error_;
};

void append(Notifications &target, Notifications source) {
    target.insert(target.end(), std::make_move_iterator(source.begin()),
                  std::make_move_iterator(source.end()));
}

} // namespace

struct Panel::Impl {
    std::shared_ptr<std::mutex> mutex = std::make_shared<std::mutex>();
    std::vector<Chord> chords;
    std::set<Slot> bases;
    std::set<Slot> held;
    std::map<Slot, std::shared_ptr<ButtonState>> buttons;
    bool active = false;

    Notifications fail(const std::string &error) {
        active = false;
        held.clear();
        Notifications observers;
        for (const auto &[slot, button] : buttons) {
            append(observers, button->fail(error));
        }
        return observers;
    }
};

Panel::Panel(std::vector<Slot> slots, std::vector<Chord> chords, std::size_t capacity)
    : impl_(std::make_unique<Impl>()) {
    if (capacity == 0) {
        throw std::invalid_argument("Input capacity must be positive");
    }
    validate_adaptation(slots, chords);
    impl_->bases = std::set<Slot>(slots.begin(), slots.end());
    auto names = impl_->bases;
    for (const auto &chord : chords) {
        if (!names.insert(chord.slot).second) {
            throw std::invalid_argument("Button slots must be distinct");
        }
    }
    impl_->chords = std::move(chords);
    for (const auto &slot : names) {
        impl_->buttons.emplace(slot, std::make_shared<ButtonState>(impl_->mutex, capacity));
    }
}

Panel::~Panel() = default;

void Panel::start() {
    std::lock_guard lock(*impl_->mutex);
    impl_->held.clear();
    for (const auto &[slot, button] : impl_->buttons) {
        button->start();
    }
    impl_->active = true;
}

std::pair<bool, Notifications> Panel::receive(const Slot &slot, bool pressed, double at) {
    std::lock_guard lock(*impl_->mutex);
    if (!impl_->active) {
        return {false, {}};
    }
    if (!impl_->bases.contains(slot)) {
        throw std::invalid_argument("Unknown base input slot");
    }
    if (impl_->held.contains(slot) == pressed) {
        return {true, {}};
    }
    auto [held, active] = hold(impl_->held, slot, pressed, impl_->chords);
    impl_->held = std::move(held);
    Notifications observers;
    for (const auto &[name, button] : impl_->buttons) {
        auto [accepted, notifications] = button->change(active.contains(name), at);
        append(observers, std::move(notifications));
        if (!accepted) {
            append(observers, impl_->fail("Input capacity exceeded"));
            return {false, std::move(observers)};
        }
    }
    return {true, std::move(observers)};
}

std::map<Slot, std::shared_ptr<Button>> Panel::buttons() const {
    std::lock_guard lock(*impl_->mutex);
    return {impl_->buttons.begin(), impl_->buttons.end()};
}

Notifications Panel::record_failure(std::string error) {
    std::lock_guard lock(*impl_->mutex);
    return impl_->fail(error);
}

Notifications Panel::close(std::string error) { return record_failure(std::move(error)); }

} // namespace opendeck

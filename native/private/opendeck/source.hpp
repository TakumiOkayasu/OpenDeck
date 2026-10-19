#pragma once

#include "opendeck/contracts.hpp"

#include <algorithm>
#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace opendeck {

using Notifications = std::vector<std::shared_ptr<Observer>>;

template <typename T> class Source final : public Input<T>, public Subject {
public:
    explicit Source(std::size_t capacity = 256) : capacity_(capacity) {
        if (capacity == 0) {
            throw std::invalid_argument("Input capacity must be positive");
        }
    }

    void start() {
        std::lock_guard lock(mutex_);
        queue_.clear();
        error_.reset();
        enabled_ = true;
    }

    void close() {
        std::lock_guard lock(mutex_);
        enabled_ = false;
        queue_.clear();
    }

    void add(std::shared_ptr<Observer> observer) override {
        if (!observer) {
            throw std::invalid_argument("Observer must not be null");
        }
        bool pending;
        {
            std::lock_guard lock(mutex_);
            if (std::find(observers_.begin(), observers_.end(), observer) != observers_.end()) {
                return;
            }
            observers_.push_back(observer);
            pending = !queue_.empty() || error_.has_value();
        }
        if (pending) {
            observer->on_change();
        }
    }

    void remove(std::shared_ptr<Observer> observer) override {
        std::lock_guard lock(mutex_);
        std::erase(observers_, observer);
    }

    std::optional<T> take() override {
        std::lock_guard lock(mutex_);
        if (error_) {
            throw InputError(*error_);
        }
        if (queue_.empty()) {
            return std::nullopt;
        }
        auto item = std::move(queue_.front());
        queue_.pop_front();
        return item;
    }

    std::pair<bool, Notifications> enqueue(T item) {
        std::lock_guard lock(mutex_);
        if (!enabled_) {
            return {false, {}};
        }
        if (queue_.size() == capacity_) {
            set_error("Input capacity exceeded");
            return {false, observers_};
        }
        queue_.push_back(std::move(item));
        return {true, observers_};
    }

    bool publish(T item) {
        auto [accepted, observers] = enqueue(std::move(item));
        notify(observers);
        return accepted;
    }

    Notifications record_failure(std::string error) {
        std::lock_guard lock(mutex_);
        if (!enabled_) {
            return {};
        }
        set_error(std::move(error));
        return observers_;
    }

    void fail(std::string error) { notify(record_failure(std::move(error))); }

    static void notify(const Notifications &observers) {
        for (const auto &observer : observers) {
            observer->on_change();
        }
    }

private:
    void set_error(std::string error) {
        queue_.clear();
        enabled_ = false;
        error_ = std::move(error);
    }

    const std::size_t capacity_;
    std::deque<T> queue_;
    Notifications observers_;
    std::mutex mutex_;
    bool enabled_ = false;
    std::optional<std::string> error_;
};

} // namespace opendeck

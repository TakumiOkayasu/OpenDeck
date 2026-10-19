#pragma once

#include "opendeck/model.hpp"

#include <map>
#include <memory>
#include <optional>
#include <stdexcept>

namespace opendeck {

class InputError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

template <typename T> class Read {
public:
    virtual ~Read() = default;
    virtual T read() const = 0;
};

template <typename T> class Input {
public:
    virtual ~Input() = default;
    virtual std::optional<T> take() = 0;
};

class Observer {
public:
    virtual ~Observer() = default;
    virtual void on_change() = 0;
};

class Subject {
public:
    virtual ~Subject() = default;
    virtual void add(std::shared_ptr<Observer> observer) = 0;
    virtual void remove(std::shared_ptr<Observer> observer) = 0;
};

class Button : public Read<bool>, public Input<Change>, public Subject {
public:
    ~Button() override = default;
};

class Action {
public:
    virtual ~Action() = default;
    virtual Result run() = 0;
};

class Link {
public:
    virtual ~Link() = default;
    virtual void open() = 0;
    virtual void close() = 0;
};

struct Product {
    std::shared_ptr<Link> link;
    std::shared_ptr<Input<Slot>> input;
    std::shared_ptr<Subject> subject;
};

struct ButtonProduct {
    std::shared_ptr<Link> link;
    std::map<Slot, std::shared_ptr<Button>> buttons;
};

template <typename T> class Factory {
public:
    virtual ~Factory() = default;
    virtual T make() = 0;
};

} // namespace opendeck

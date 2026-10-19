#include "opendeck/contracts.hpp"

#include <concepts>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

using namespace opendeck;

// 同じソースを、コンパイル拒否を確認する負例にも使う。
#if defined(OPENDECK_NEGATIVE_ABSTRACT)
int main() {
    class Missing final : public Button {};
    Missing missing;
}
#elif defined(OPENDECK_NEGATIVE_METHOD)
void unsupported(Read<bool> &state) { state.take(); }
int main() {}
#elif defined(OPENDECK_NEGATIVE_SIGNATURE)
int main() {
    class Wrong final : public Read<bool> {
    public:
        bool read() { return false; }
    };
    Wrong wrong;
}
#else
static_assert(std::is_abstract_v<Read<bool>>);
static_assert(std::is_abstract_v<Input<Change>>);
static_assert(std::is_abstract_v<Observer>);
static_assert(std::is_abstract_v<Subject>);
static_assert(std::is_abstract_v<Button>);
static_assert(std::is_abstract_v<Action>);
static_assert(std::is_abstract_v<Link>);
static_assert(std::is_abstract_v<Factory<int>>);
static_assert(std::is_abstract_v<Factory<Product>>);
static_assert(std::is_abstract_v<Factory<ButtonProduct>>);
static_assert(std::same_as<decltype(Product{}.link), std::shared_ptr<Link>>);
static_assert(std::same_as<decltype(Product{}.input), std::shared_ptr<Input<Slot>>>);
static_assert(std::same_as<decltype(Product{}.subject), std::shared_ptr<Subject>>);
static_assert(std::same_as<decltype(ButtonProduct{}.link), std::shared_ptr<Link>>);
static_assert(
    std::same_as<decltype(ButtonProduct{}.buttons), std::map<Slot, std::shared_ptr<Button>>>);
static_assert(std::derived_from<Button, Read<bool>>);
static_assert(std::derived_from<Button, Input<Change>>);
static_assert(std::derived_from<Button, Subject>);
static_assert(std::has_virtual_destructor_v<Read<std::string>>);
static_assert(std::has_virtual_destructor_v<Input<Slot>>);
static_assert(std::has_virtual_destructor_v<Observer>);
static_assert(std::has_virtual_destructor_v<Subject>);
static_assert(std::has_virtual_destructor_v<Button>);
static_assert(std::has_virtual_destructor_v<Action>);
static_assert(std::has_virtual_destructor_v<Link>);
static_assert(std::has_virtual_destructor_v<Factory<int>>);

namespace {
class Text final : public Read<std::string> {
public:
    std::string read() const override { return "generic value"; }
};

class Concrete final : public Action {
public:
    explicit Concrete(bool &destroyed) : destroyed_(destroyed) {}
    ~Concrete() override { destroyed_ = true; }
    Result run() override { return {Status::done, "finished"}; }

private:
    bool &destroyed_;
};

class Session final : public Link, public Input<Slot>, public Subject {
public:
    explicit Session(int &opens) : opens_(opens) {}
    void open() override {
        pending_ = Slot{"ready"};
        ++opens_;
    }
    void close() override { pending_.reset(); }
    std::optional<Slot> take() override { return std::exchange(pending_, std::nullopt); }
    void add(std::shared_ptr<Observer>) override {}
    void remove(std::shared_ptr<Observer>) override {}

private:
    int &opens_;
    std::optional<Slot> pending_;
};

class Kit final : public Factory<Product> {
public:
    explicit Kit(int &opens) : opens_(opens) {}
    Product make() override {
        const auto session = std::make_shared<Session>(opens_);
        return {session, session, session};
    }

private:
    int &opens_;
};

void factory_returns_related_capabilities_without_opening_the_connection() {
    int opens = 0;
    Kit concrete(opens);
    Factory<Product> &factory = concrete;
    const auto product = factory.make();
    if (!product.link || !product.input || !product.subject || opens != 0 ||
        product.input->take().has_value()) {
        throw std::runtime_error("Factory must return unopened related capabilities");
    }
    product.link->open();
    if (opens != 1 || product.input->take() != Slot{"ready"}) {
        throw std::runtime_error("Related capabilities must use the same connection");
    }
    product.link->close();
    if (product.input->take().has_value()) {
        throw std::runtime_error("Closing the Link must affect its related input");
    }
}
} // namespace

int main() {
    const Text text;
    const Read<std::string> &read = text;
    if (read.read() != "generic value") {
        throw std::runtime_error("Read must preserve its value type");
    }
    bool destroyed = false;
    {
        const auto concrete = std::make_shared<Concrete>(destroyed);
        std::shared_ptr<Action> action = concrete;
        if (action->run() != Result{Status::done, "finished"}) {
            throw std::runtime_error("Action dispatch must preserve its result");
        }
    }
    if (!destroyed) {
        throw std::runtime_error("Destruction through a contract must be safe");
    }
    factory_returns_related_capabilities_without_opening_the_connection();
}
#endif

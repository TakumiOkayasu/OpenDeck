#include "opendeck/contracts.hpp"
#include "opendeck/panel.hpp"
#include "opendeck/recognition.hpp"
#include "opendeck/runtime.hpp"
#include "opendeck/source.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstdint>
#include <map>
#include <memory>
#include <utility>

namespace py = pybind11;
using namespace opendeck;

namespace {

py::object method(py::handle object, const char *name) {
    auto value = object.attr(name);
    if (!PyCallable_Check(value.ptr())) {
        throw py::type_error(std::string(name) + " must be callable");
    }
    return value;
}

std::set<Slot> slots(py::iterable values) {
    std::set<Slot> result;
    for (auto value : values)
        result.insert(Slot{py::cast<std::string>(value)});
    return result;
}

std::vector<Slot> ordered_slots(py::iterable values) {
    std::vector<Slot> result;
    for (auto value : values)
        result.push_back(Slot{py::cast<std::string>(value)});
    return result;
}

py::tuple names(const std::vector<Slot> &values) {
    py::tuple result(values.size());
    for (std::size_t i = 0; i < values.size(); ++i)
        result[i] = py::str(values[i].name);
    return result;
}

py::frozenset names(const std::set<Slot> &values) {
    py::set result;
    for (const auto &value : values)
        result.add(py::str(value.name));
    return py::frozenset(result);
}

std::vector<Chord> chords(py::iterable values) {
    std::vector<Chord> result;
    for (auto value : values) {
        auto pair = py::cast<py::tuple>(value);
        result.push_back(Chord{slots(pair[0]), Slot{py::cast<std::string>(pair[1])}});
    }
    return result;
}

py::object change(const std::optional<Change> &value) {
    if (!value)
        return py::none();
    return py::module_::import("opendeck.model").attr("Change")(value->pressed, value->at);
}

Status status(const std::string &value) {
    if (value == "done")
        return Status::done;
    if (value == "failed")
        return Status::failed;
    if (value == "unknown")
        return Status::unknown;
    throw py::type_error("Action.run must return a Result with a valid status");
}

py::object result(const std::optional<Result> &value) {
    if (!value)
        return py::none();
    const char *text = value->status == Status::done     ? "done"
                       : value->status == Status::failed ? "failed"
                                                         : "unknown";
    auto model = py::module_::import("opendeck.model");
    return model.attr("Result")(model.attr("Status")(text), value->detail);
}

class Listener final : public Observer {
public:
    explicit Listener(py::object value)
        : object(std::move(value)), callback(method(object, "on_change")) {}
    void on_change() override {
        py::gil_scoped_acquire acquire;
        callback();
    }
    py::object object;

private:
    py::object callback;
};

// Pythonの参照はbindingが所有し、coreのロック内では解放しない。
class Listeners {
public:
    std::shared_ptr<Listener> get(py::object object) {
        auto found = entries.find(object.ptr());
        if (found != entries.end())
            return found->second;
        auto listener = std::make_shared<Listener>(std::move(object));
        entries.emplace(listener->object.ptr(), listener);
        return listener;
    }
    std::shared_ptr<Listener> find(py::handle object) const {
        auto found = entries.find(object.ptr());
        return found == entries.end() ? nullptr : found->second;
    }
    void erase(py::handle object) { entries.erase(object.ptr()); }

private:
    std::map<PyObject *, std::shared_ptr<Listener>> entries;
};

py::tuple notifications(const Notifications &observers) {
    py::tuple result(observers.size());
    for (std::size_t i = 0; i < observers.size(); ++i) {
        result[i] = std::static_pointer_cast<Listener>(observers[i])->object;
    }
    return result;
}

class SourceBridge {
public:
    explicit SourceBridge(std::size_t capacity) : source(capacity) {}
    void start() {
        source.start();
        discard_payloads();
    }
    void close() {
        source.close();
        discard_payloads();
    }
    void add(py::object observer) { source.add(listeners.get(std::move(observer))); }
    void remove(py::object observer) {
        auto listener = listeners.find(observer);
        if (!listener)
            return;
        source.remove(listener);
        listeners.erase(observer);
    }
    py::tuple enqueue(py::object value) {
        const auto token = next++;
        auto [accepted, observers] = source.enqueue(token);
        if (accepted)
            payloads.emplace(token, std::move(value));
        else
            discard_payloads();
        return py::make_tuple(accepted, notifications(observers));
    }
    py::tuple fail(const std::string &error) {
        auto observers = source.record_failure(error);
        discard_payloads();
        return notifications(observers);
    }
    py::object take() {
        auto token = source.take();
        if (!token)
            return py::none();
        auto item = payloads.extract(*token);
        if (item.empty())
            throw std::logic_error("Missing input payload");
        return std::move(item.mapped());
    }

private:
    void discard_payloads() {
        std::map<std::uint64_t, py::object> discarded;
        payloads.swap(discarded);
    }
    Listeners listeners;
    Source<std::uint64_t> source;
    std::map<std::uint64_t, py::object> payloads;
    std::uint64_t next = 0;
};

class ButtonView {
public:
    explicit ButtonView(std::shared_ptr<Button> value) : button(std::move(value)) {}
    bool read() const {
        py::gil_scoped_release release;
        return button->read();
    }
    py::object take() {
        std::optional<Change> value;
        {
            py::gil_scoped_release release;
            value = button->take();
        }
        return change(value);
    }
    void add(py::object observer) {
        auto listener = listeners.get(std::move(observer));
        // addは未処理履歴の通知を行うため、GILを保持したまま呼ぶ。
        button->add(listener);
    }
    void remove(py::object observer) {
        auto listener = listeners.find(observer);
        if (!listener)
            return;
        button->remove(listener);
        listeners.erase(observer);
    }

private:
    Listeners listeners;
    std::shared_ptr<Button> button;
};

// viewを独立した型にし、公開面を具体実装や他の能力へ広げない。
struct ReadView {
    py::object read;
};
struct InputView {
    py::object take;
};
struct SubjectView {
    py::object add;
    py::object remove;
};

class PanelBridge {
public:
    PanelBridge(py::iterable inputs, py::iterable definitions, std::size_t capacity)
        : panel(ordered_slots(inputs), chords(definitions), capacity) {
        for (const auto &[slot, button] : panel.buttons()) {
            views.emplace(slot.name, std::make_shared<ButtonView>(button));
        }
    }
    void start() {
        py::gil_scoped_release release;
        panel.start();
    }
    py::tuple receive(const std::string &slot, bool pressed, double at) {
        std::pair<bool, Notifications> accepted;
        {
            py::gil_scoped_release release;
            accepted = panel.receive(Slot{slot}, pressed, at);
        }
        return py::make_tuple(accepted.first, notifications(accepted.second));
    }
    py::tuple fail(const std::string &error) {
        Notifications observers;
        {
            py::gil_scoped_release release;
            observers = panel.record_failure(error);
        }
        return notifications(observers);
    }
    py::tuple close(const std::string &error) {
        Notifications observers;
        {
            py::gil_scoped_release release;
            observers = panel.close(error);
        }
        return notifications(observers);
    }
    const std::map<std::string, std::shared_ptr<ButtonView>> &buttons() const { return views; }

private:
    Panel panel;
    std::map<std::string, std::shared_ptr<ButtonView>> views;
};

class Operation final : public Action {
public:
    explicit Operation(py::object value)
        : object(std::move(value)), callback(method(object, "run")) {}
    Result run() override {
        py::gil_scoped_acquire acquire;
        auto value = callback();
        auto model = py::module_::import("opendeck.model");
        if (!py::isinstance(value, model.attr("Result")))
            throw py::type_error("Action.run must return Result");
        return Result{status(py::cast<std::string>(value.attr("status"))),
                      py::cast<std::string>(value.attr("detail"))};
    }
    py::object object;

private:
    py::object callback;
};

class BindingBridge {
public:
    explicit BindingBridge(py::dict actions) : binding(make(actions)) {}
    py::object select(const std::string &slot) const {
        auto action = binding.select(Slot{slot});
        return action ? std::static_pointer_cast<Operation>(action)->object : py::none();
    }
    const Binding binding;

private:
    static std::map<Slot, std::shared_ptr<Action>> make(py::dict actions) {
        std::map<Slot, std::shared_ptr<Action>> result;
        for (auto item : actions) {
            result.emplace(
                Slot{py::cast<std::string>(item.first)},
                std::make_shared<Operation>(py::reinterpret_borrow<py::object>(item.second)));
        }
        return result;
    }
};

class SlotInput final : public Input<Slot> {
public:
    explicit SlotInput(py::handle object) : callback(method(object, "take")) {}
    std::optional<Slot> take() override {
        py::gil_scoped_acquire acquire;
        auto value = callback();
        if (value.is_none())
            return std::nullopt;
        return Slot{py::cast<std::string>(value)};
    }

private:
    py::object callback;
};

} // namespace

PYBIND11_MODULE(_native, m) {
    py::register_exception<InputError>(m, "InputError", PyExc_RuntimeError);
    py::class_<SourceBridge, std::shared_ptr<SourceBridge>>(m, "Source")
        .def(py::init<std::size_t>(), py::arg("capacity") = 256)
        .def("start", &SourceBridge::start)
        .def("close", &SourceBridge::close)
        .def("add", &SourceBridge::add)
        .def("remove", &SourceBridge::remove)
        .def("enqueue", &SourceBridge::enqueue)
        .def("record_failure", &SourceBridge::fail)
        .def("take", &SourceBridge::take);
    py::class_<ButtonView, std::shared_ptr<ButtonView>>(m, "Button")
        .def("read", &ButtonView::read)
        .def("take", &ButtonView::take)
        .def("add", &ButtonView::add)
        .def("remove", &ButtonView::remove);
    py::class_<ReadView>(m, "ReadView").def("read", [](const ReadView &view) {
        return view.read();
    });
    py::class_<InputView>(m, "InputView").def("take", [](const InputView &view) {
        return view.take();
    });
    py::class_<SubjectView>(m, "SubjectView")
        .def("add", [](const SubjectView &view, py::object o) { view.add(o); })
        .def("remove", [](const SubjectView &view, py::object o) { view.remove(o); });
    m.def(
        "read_view", [](py::object value) { return ReadView{method(value, "read")}; },
        py::arg("state").none(false));
    m.def(
        "input_view", [](py::object value) { return InputView{method(value, "take")}; },
        py::arg("input").none(false));
    m.def(
        "subject_view",
        [](py::object value) { return SubjectView{method(value, "add"), method(value, "remove")}; },
        py::arg("subject").none(false));
    py::class_<PanelBridge>(m, "Panel")
        .def(py::init<py::iterable, py::iterable, std::size_t>(), py::arg("slots"),
             py::arg("chords"), py::arg("capacity") = 256)
        .def("start", &PanelBridge::start)
        .def("receive", &PanelBridge::receive)
        .def("record_failure", &PanelBridge::fail)
        .def("close", &PanelBridge::close, py::arg("error") = "Button input closed")
        .def_property_readonly("buttons", &PanelBridge::buttons);
    py::class_<BindingBridge>(m, "Binding")
        .def(py::init<py::dict>())
        .def("select", &BindingBridge::select);
    m.def("drain", [](py::object input, const BindingBridge &binding, py::function report) {
        SlotInput source(input);
        py::gil_scoped_release release;
        return drain(source, binding.binding,
                     [&](const Slot &slot, const std::optional<Result> &value) {
                         py::gil_scoped_acquire acquire;
                         report(py::str(slot.name), result(value));
                     });
    });
    m.def("validate_state", [](py::iterable held, py::iterable claimed) {
        validate_state(State{slots(held), slots(claimed)});
    });
    m.def("apply", [](py::iterable held, py::iterable claimed, const std::string &slot,
                      bool pressed, py::iterable definitions) {
        auto [following, emitted] =
            apply(State{slots(held), slots(claimed)}, Slot{slot}, pressed, chords(definitions));
        return py::make_tuple(names(following.held), names(following.claimed), names(emitted));
    });
    m.def("hold", [](py::iterable held, const std::string &slot, bool pressed,
                     py::iterable definitions) {
        auto [following, active] = hold(slots(held), Slot{slot}, pressed, chords(definitions));
        return py::make_tuple(names(following), names(active));
    });
    m.def("validate_adaptation", [](py::iterable inputs, py::iterable definitions) {
        validate_adaptation(ordered_slots(inputs), chords(definitions));
    });
}

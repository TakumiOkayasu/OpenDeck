import gc
import weakref

import pytest

from opendeck import Change, InputError, Slot, input_view, read_view, subject_view
from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.ports import (
    Action,
    Button,
    ButtonFactory,
    Factory,
    Input,
    Link,
    Observer,
    Read,
    Subject,
)
from opendeck.source import Source


@pytest.mark.parametrize(
    "contract",
    [Read, Input, Observer, Subject, Action, Link, Factory, ButtonFactory, Button],
)
def test_incomplete_contract_implementation_cannot_be_instantiated(contract):
    incomplete = type("Incomplete", (contract,), {})
    with pytest.raises(TypeError, match="abstract"):
        incomplete()


def test_explicit_read_implementation_exposes_only_its_declared_capability():
    class Current(Read[str]):
        def read(self) -> str:
            return "available"

    current = Current()
    assert current.read() == "available"
    assert not hasattr(current, "take")
    assert not hasattr(current, "write")


def test_read_view_cannot_consume_history_or_change_the_button():
    primary = Slot("primary")
    product = ReplayFactory({1: primary}, (), (Edge(1, True),)).make_buttons(
        clock=lambda: 12.0
    )
    button = product.buttons[primary]
    state = read_view(button)
    assert isinstance(state, Read)
    assert not isinstance(state, Input)
    for method in ("take", "add", "remove", "write", "set", "publish"):
        assert not hasattr(state, method)
    with pytest.raises(InputError):
        state.read()
    try:
        product.link.open()
        assert state.read() is True
        assert state.read() is True
        assert button.take() == Change(True, 12.0)
        assert button.take() is None
    finally:
        product.link.close()
    with pytest.raises(InputError):
        state.read()


def test_input_and_subject_views_expose_only_the_requested_capabilities():
    primary = Slot("primary")
    product = ReplayFactory({1: primary}, (), (Edge(1, True),)).make_buttons(
        clock=lambda: 7.0
    )
    button = product.buttons[primary]
    changes = input_view(button)
    subject = subject_view(button)
    assert isinstance(changes, Input)
    assert not isinstance(changes, Read)
    assert isinstance(subject, Subject)
    for method in ("read", "add", "remove", "write", "publish"):
        assert not hasattr(changes, method)
    for method in ("read", "take", "write", "publish"):
        assert not hasattr(subject, method)
    notifications: list[None] = []

    class Listener(Observer):
        def on_change(self) -> None:
            notifications.append(None)

    listener = Listener()
    subject.add(listener)
    subject.add(listener)
    try:
        product.link.open()
        assert notifications == [None]
        assert changes.take() == Change(True, 7.0)
        assert changes.take() is None
        assert button.read() is True
    finally:
        subject.remove(listener)
        product.link.close()


def test_native_source_preserves_arbitrary_python_payload_identity():
    first = {"state": [True]}
    second = object()
    source = Source[object]()
    source.start()
    assert source.publish(first)
    assert source.publish(second)
    assert source.publish(first)
    assert source.take() is first
    assert source.take() is second
    assert source.take() is first
    assert source.take() is None
    source.close()


def test_overflow_without_observers_releases_discarded_python_payloads():
    class Payload:
        pass

    source = Source[object](capacity=1)
    source.start()
    payload = Payload()
    retained = weakref.ref(payload)
    assert source.publish(payload)
    del payload
    gc.collect()
    assert retained() is not None
    assert not source.publish(object())
    gc.collect()
    assert retained() is None
    with pytest.raises(InputError, match="capacity"):
        source.take()


def test_signal_factory_input_exposes_only_consumption():
    primary = Slot("primary")
    product = ReplayFactory({1: primary}, (), ()).make()
    assert isinstance(product.input, Input)
    assert product.input.take() is None
    for method in ("start", "close", "publish", "enqueue", "add", "remove"):
        assert not hasattr(product.input, method)


def test_signal_factory_subject_does_not_expose_consumption_or_production():
    primary = Slot("primary")
    product = ReplayFactory({1: primary}, (), ()).make()
    assert isinstance(product.subject, Subject)
    for method in ("take", "start", "close", "publish", "enqueue", "record_failure"):
        assert not hasattr(product.subject, method)

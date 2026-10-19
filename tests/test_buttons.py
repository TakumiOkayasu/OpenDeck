from collections.abc import MutableMapping
from dataclasses import FrozenInstanceError
from operator import setitem
from typing import cast

import pytest

from opendeck import Button, ButtonFactory, Change, Chord, Input, InputError, Read, Slot
from opendeck.adapters.replay import Edge, ReplayFactory


def test_extension_observes_button_start_and_current_held_state():
    slot = Slot("primary")
    product = ReplayFactory({1: slot}, (), (Edge(1, True),)).make_buttons(
        clock=lambda: 12.0
    )
    button: Button = product.buttons[slot]
    with pytest.raises(InputError):
        button.read()
    try:
        product.link.open()
        assert button.read() is True
        assert button.take() == Change(True, 12.0)
        assert button.take() is None
    finally:
        product.link.close()


def test_history_preserves_start_and_release_while_read_returns_latest_state():
    slot = Slot("primary")
    times = iter((10.0, 14.5))
    product = ReplayFactory(
        {1: slot},
        (),
        (Edge(1, False), Edge(9, True), Edge(1, True), Edge(1, True), Edge(1, False)),
    ).make_buttons(clock=lambda: next(times))
    button = product.buttons[slot]
    try:
        product.link.open()
        assert button.read() is False
        start, release = button.take(), button.take()
        assert start == Change(True, 10.0)
        assert release == Change(False, 14.5)
        assert button.take() is None
        assert start is not None
        with pytest.raises(FrozenInstanceError):
            start.__setattr__("pressed", False)
    finally:
        product.link.close()


def test_chord_state_starts_when_all_held_and_ends_on_first_release():
    a, b, together = Slot("a"), Slot("b"), Slot("together")
    chord = Chord(frozenset({a, b}), together)
    times = iter((1.0, 2.0, 3.0, 4.0))
    product = ReplayFactory(
        {1: a, 2: b},
        (chord,),
        (Edge(1, True), Edge(2, True), Edge(1, False), Edge(2, False)),
    ).make_buttons(clock=lambda: next(times))
    try:
        product.link.open()
        for slot, expected in (
            (a, (Change(True, 1.0), Change(False, 3.0))),
            (b, (Change(True, 2.0), Change(False, 4.0))),
            (together, (Change(True, 2.0), Change(False, 3.0))),
        ):
            button = product.buttons[slot]
            assert button.read() is False
            assert (button.take(), button.take()) == expected
            assert button.take() is None
    finally:
        product.link.close()


def test_close_invalidates_state_and_pending_history_without_synthetic_release():
    slot = Slot("primary")
    product = ReplayFactory({1: slot}, (), (Edge(1, True),)).make_buttons()
    button = product.buttons[slot]
    product.link.open()
    product.link.close()
    with pytest.raises(InputError, match="closed"):
        button.read()
    with pytest.raises(InputError, match="closed"):
        button.take()
    product.link.open()
    try:
        assert button.read() is True
        start = button.take()
        assert start is not None
        assert start.pressed is True
        assert button.take() is None
    finally:
        product.link.close()


def test_late_observer_is_notified_of_pending_changes_and_can_be_removed():
    slot = Slot("primary")
    product = ReplayFactory({1: slot}, (), (Edge(1, True),)).make_buttons()
    button = product.buttons[slot]
    calls = []

    class Listener:
        def on_change(self):
            calls.append(None)

    listener = Listener()
    product.link.open()
    button.add(listener)
    assert calls == [None]
    button.remove(listener)
    product.link.close()
    assert calls == [None]


def test_finite_button_replay_has_capacity_for_each_recorded_change():
    slot = Slot("primary")
    product = ReplayFactory(
        {1: slot}, (), (Edge(1, True), Edge(1, False)) * 300
    ).make_buttons()
    try:
        product.link.open()
        button = product.buttons[slot]
        assert sum(1 for _ in iter(button.take, None)) == 600
        assert button.read() is False
    finally:
        product.link.close()


def test_button_declarations_are_immutable_and_independent_per_product():
    slot = Slot("primary")
    factory = ReplayFactory({1: slot}, (), (Edge(1, True),))
    first, second = factory.make_buttons(), factory.make_buttons()
    with pytest.raises(TypeError):
        setitem(
            cast(MutableMapping[Slot, Button], first.buttons),
            slot,
            second.buttons[slot],
        )
    first.link.open()
    try:
        assert first.buttons[slot].read() is True
        with pytest.raises(InputError):
            second.buttons[slot].read()
    finally:
        first.link.close()
        second.link.close()


@pytest.mark.parametrize("target", ["a", "together"])
def test_colliding_button_identities_are_rejected(target):
    a, b, together = Slot("a"), Slot("b"), Slot("together")
    chords = (
        Chord(frozenset({a, b}), together),
        Chord(frozenset({a, b}), Slot(target)),
    )
    with pytest.raises(ValueError, match="distinct"):
        ReplayFactory({1: a, 2: b}, chords, ()).make_buttons()


def test_failed_timestamp_acquisition_invalidates_every_button():
    a, b = Slot("a"), Slot("b")

    def failed_clock():
        raise RuntimeError("clock failed")

    product = ReplayFactory({1: a, 2: b}, (), (Edge(1, True),)).make_buttons(
        clock=failed_clock
    )
    try:
        with pytest.raises(RuntimeError, match="clock failed"):
            product.link.open()
        for button in product.buttons.values():
            with pytest.raises(InputError, match="clock failed"):
                button.read()
            with pytest.raises(InputError, match="clock failed"):
                button.take()
    finally:
        product.link.close()


def test_extension_receives_only_the_capabilities_it_uses():
    slot = Slot("primary")
    factory: ButtonFactory = ReplayFactory({1: slot}, (), (Edge(1, True),))
    product = factory.make_buttons()

    def current(state: Read[bool]):
        return state.read()

    def following(input: Input[Change]):
        return input.take()

    try:
        product.link.open()
        button = product.buttons[slot]
        assert current(button) is True
        change = following(button)
        assert change is not None
        assert change.pressed is True
    finally:
        product.link.close()

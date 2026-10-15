from dataclasses import FrozenInstanceError

import pytest

from opendeck.bindings import Binding
from opendeck.model import Result, Slot, Status


class Operation:
    def run(self) -> Result:
        raise AssertionError("Selecting an action must not execute it")


def test_selection_uses_a_stable_snapshot_without_executing() -> None:
    slot = Slot("launch")
    action = Operation()
    configured = {slot: action}
    bindings = Binding(configured)
    configured.clear()

    assert bindings.select(slot) is action
    assert bindings.select(slot) is action
    assert bindings.select(Slot("unassigned")) is None


def test_bindings_cannot_be_reassigned() -> None:
    bindings = Binding({})
    with pytest.raises(FrozenInstanceError):
        bindings._actions = {}


def test_selection_preserves_the_supplied_action() -> None:
    class Operation:
        def run(self) -> Result:
            return Result(Status.DONE)

    action = Operation()
    bindings = Binding({Slot("launch"): action})
    selected = bindings.select(Slot("launch"))

    assert selected is action
    assert selected.run().status is Status.DONE

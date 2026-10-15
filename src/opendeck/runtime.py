from collections.abc import Callable
from threading import Event

from .bindings import Binding
from .model import Result, Slot
from .ports import Input


class Wake:
    def __init__(self) -> None:
        self._event = Event()

    def on_change(self) -> None:
        self._event.set()

    def wait(self) -> None:
        self._event.wait()
        self._event.clear()


def drain(
    input: Input[Slot],
    binding: Binding,
    report: Callable[[Slot, Result | None], None],
) -> int:
    count = 0
    while (slot := input.take()) is not None:
        action = binding.select(slot)
        result = None if action is None else action.run()
        report(slot, result)
        count += 1
    return count

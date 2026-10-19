from collections.abc import Callable
from threading import Event

from . import _native as core  # pyright: ignore[reportMissingModuleSource]
from .bindings import Binding
from .model import Result, Slot
from .ports import Input, Observer


class Wake(Observer):
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
    return core.drain(input, binding._native, report)

import logging
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Protocol

from .. import _native  # pyright: ignore[reportMissingModuleSource]
from ..model import Chord, Slot
from ..ports import Button, InputError, Observer
from ..recognition import State, apply
from ..source import Source

_LOGGER = logging.getLogger(__name__)


class Receiver(Protocol):
    def start(self) -> None: ...
    def receive(
        self, slot: Slot, pressed: bool
    ) -> tuple[bool, tuple[Observer, ...]]: ...
    def record_failure(self, error: Exception | str) -> tuple[Observer, ...]: ...
    def close(self, error: Exception | None = None) -> tuple[Observer, ...]: ...


class Signals:
    def __init__(self, source: Source[Slot], chords: tuple[Chord, ...]) -> None:
        self._source = source
        self._chords = chords
        self._state = State()

    def start(self) -> None:
        self._state = State()
        self._source.start()

    def receive(self, slot: Slot, pressed: bool) -> tuple[bool, tuple[Observer, ...]]:
        self._state, slots = apply(self._state, slot, pressed, self._chords)
        notifications: tuple[Observer, ...] = ()
        for recognized in slots:
            accepted, observers = self._source.enqueue(recognized)
            notifications += observers
            if not accepted:
                self._state = State()
                return False, notifications
            _LOGGER.debug("Recognized input: %s", recognized)
        return True, notifications

    def record_failure(self, error: Exception | str) -> tuple[Observer, ...]:
        self._state = State()
        return self._source.record_failure(error)

    def close(self, error: Exception | None = None) -> tuple[Observer, ...]:
        self._state = State()
        self._source.close()
        return ()


class Panel:
    def __init__(
        self,
        slots: Iterable[Slot],
        chords: tuple[Chord, ...],
        clock: Callable[[], float],
        capacity: int = 256,
    ) -> None:
        self._panel = _native.Panel(
            tuple(slots),
            tuple((chord.members, chord.slot) for chord in chords),
            capacity,
        )
        self._clock = clock
        self._buttons = MappingProxyType(self._panel.buttons)

    @property
    def buttons(self) -> Mapping[Slot, Button]:
        return self._buttons

    def start(self) -> None:
        self._panel.start()

    def receive(self, slot: Slot, pressed: bool) -> tuple[bool, tuple[Observer, ...]]:
        try:
            unchanged = self._buttons[slot].read() == pressed
        except InputError:
            return False, ()
        if unchanged:
            return True, ()
        return self._panel.receive(slot, pressed, self._clock())

    def record_failure(self, error: Exception | str) -> tuple[Observer, ...]:
        return self._panel.record_failure(str(error))

    def close(self, error: Exception | None = None) -> tuple[Observer, ...]:
        return self._panel.close(
            str(error) if error is not None else "Button input closed"
        )

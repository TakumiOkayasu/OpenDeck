import logging
from collections.abc import Callable, Iterable, Mapping
from threading import RLock
from types import MappingProxyType
from typing import Protocol

from ..model import Change, Chord, Slot
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


def hold(
    held: frozenset[Slot], slot: Slot, pressed: bool, chords: tuple[Chord, ...]
) -> tuple[frozenset[Slot], frozenset[Slot]]:
    following = held | {slot} if pressed else held - {slot}
    active = following | {chord.slot for chord in chords if chord.members <= following}
    return following, active


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


class _Button:
    def __init__(self, lock: RLock, capacity: int) -> None:
        self._lock = lock
        self._source = Source[Change](capacity)
        self._source.start()
        self._pressed: bool | None = None
        self._error: InputError | None = None

    def read(self) -> bool:
        with self._lock:
            if self._error is not None:
                raise self._error
            if self._pressed is None:
                raise InputError("Button input has not started")
            return self._pressed

    def take(self) -> Change | None:
        with self._lock:
            return self._source.take()

    def add(self, observer: Observer) -> None:
        self._source.add(observer)

    def remove(self, observer: Observer) -> None:
        self._source.remove(observer)

    def start(self) -> None:
        self._source.start()
        self._pressed = False
        self._error = None

    def change(self, pressed: bool, at: float) -> tuple[bool, tuple[Observer, ...]]:
        if self._pressed == pressed:
            return True, ()
        self._pressed = pressed
        return self._source.enqueue(Change(pressed, at))

    def fail(self, error: InputError) -> tuple[Observer, ...]:
        if self._error is not None:
            return ()
        self._pressed = None
        self._error = error
        return self._source.record_failure(error)


class Panel:
    def __init__(
        self,
        slots: Iterable[Slot],
        chords: tuple[Chord, ...],
        clock: Callable[[], float],
        capacity: int = 256,
    ) -> None:
        names = (*slots, *(chord.slot for chord in chords))
        if len(set(names)) != len(names):
            raise ValueError("Button slots must be distinct")
        self._lock = RLock()
        self._chords = chords
        self._clock = clock
        self._held: frozenset[Slot] = frozenset()
        self._active = False
        self._buttons = {slot: _Button(self._lock, capacity) for slot in names}

    @property
    def buttons(self) -> Mapping[Slot, Button]:
        return MappingProxyType(self._buttons)

    def start(self) -> None:
        with self._lock:
            self._held = frozenset()
            for button in self._buttons.values():
                button.start()
            self._active = True

    def receive(self, slot: Slot, pressed: bool) -> tuple[bool, tuple[Observer, ...]]:
        with self._lock:
            if not self._active:
                return False, ()
            if (slot in self._held) == pressed:
                return True, ()
            self._held, active = hold(self._held, slot, pressed, self._chords)
            at = self._clock()
            notifications: tuple[Observer, ...] = ()
            for name, button in self._buttons.items():
                accepted, observers = button.change(name in active, at)
                notifications += observers
                if not accepted:
                    notifications += self.record_failure(
                        InputError("Input capacity exceeded")
                    )
                    return False, notifications
            return True, notifications

    def record_failure(self, error: Exception | str) -> tuple[Observer, ...]:
        with self._lock:
            self._active = False
            self._held = frozenset()
            failure = error if isinstance(error, InputError) else InputError(str(error))
            return tuple(
                observer
                for button in self._buttons.values()
                for observer in button.fail(failure)
            )

    def close(self, error: Exception | None = None) -> tuple[Observer, ...]:
        return self.record_failure(
            error if error is not None else InputError("Button input closed")
        )

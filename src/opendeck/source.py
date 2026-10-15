from collections import deque
from threading import Lock

from .ports import Observer


class InputError(RuntimeError):
    pass


class Source[T]:
    def __init__(self, capacity: int = 256) -> None:
        if capacity < 1:
            raise ValueError("Input capacity must be positive")
        self._capacity = capacity
        self._queue: deque[T] = deque()
        self._observers: list[Observer] = []
        self._lock = Lock()
        self._enabled = False
        self._error: InputError | None = None

    def start(self) -> None:
        with self._lock:
            self._queue.clear()
            self._error = None
            self._enabled = True

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._queue.clear()

    def add(self, observer: Observer) -> None:
        with self._lock:
            if any(item is observer for item in self._observers):
                return
            self._observers.append(observer)
            pending = bool(self._queue) or self._error is not None
        if pending:
            observer.on_change()

    def remove(self, observer: Observer) -> None:
        with self._lock:
            self._observers = [item for item in self._observers if item is not observer]

    def publish(self, item: T) -> bool:
        accepted, observers = self.enqueue(item)
        self.notify(observers)
        return accepted

    def enqueue(self, item: T) -> tuple[bool, tuple[Observer, ...]]:
        with self._lock:
            if not self._enabled:
                return False, ()
            if len(self._queue) == self._capacity:
                self._set_error(InputError("Input capacity exceeded"))
                accepted = False
            else:
                self._queue.append(item)
                accepted = True
            return accepted, tuple(self._observers)

    def fail(self, error: Exception | str) -> None:
        self.notify(self.record_failure(error))

    def record_failure(self, error: Exception | str) -> tuple[Observer, ...]:
        with self._lock:
            if not self._enabled:
                return ()
            if not isinstance(error, InputError):
                error = InputError(str(error))
            self._set_error(error)
            return tuple(self._observers)

    @staticmethod
    def notify(observers: tuple[Observer, ...]) -> None:
        for observer in observers:
            observer.on_change()

    def take(self) -> T | None:
        with self._lock:
            if self._error is not None:
                raise self._error
            if not self._queue:
                return None
            return self._queue.popleft()

    def _set_error(self, error: InputError) -> None:
        self._queue.clear()
        self._enabled = False
        self._error = error

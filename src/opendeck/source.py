from typing import cast

from . import _native as core  # pyright: ignore[reportMissingModuleSource]
from .ports import Input, Observer, Subject
from .ports import InputError as InputError


class Source[T](Input[T], Subject):
    def __init__(self, capacity: int = 256) -> None:
        self._native = core.Source(capacity)

    @property
    def input(self) -> Input[T]:
        return cast(Input[T], core.input_view(self._native))

    @property
    def subject(self) -> Subject:
        return core.subject_view(self._native)

    def start(self) -> None:
        self._native.start()

    def close(self) -> None:
        self._native.close()

    def add(self, observer: Observer) -> None:
        self._native.add(observer)

    def remove(self, observer: Observer) -> None:
        self._native.remove(observer)

    def publish(self, item: T) -> bool:
        accepted, observers = self.enqueue(item)
        self.notify(observers)
        return accepted

    def enqueue(self, item: T) -> tuple[bool, tuple[Observer, ...]]:
        return self._native.enqueue(item)

    def fail(self, error: Exception | str) -> None:
        self.notify(self.record_failure(error))

    def record_failure(self, error: Exception | str) -> tuple[Observer, ...]:
        return self._native.record_failure(str(error))

    @staticmethod
    def notify(observers: tuple[Observer, ...]) -> None:
        for observer in observers:
            observer.on_change()

    def take(self) -> T | None:
        return cast(T | None, self._native.take())

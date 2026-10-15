from dataclasses import dataclass
from typing import Protocol

from .model import Result, Slot


class Input[T](Protocol):
    def take(self) -> T | None: ...


class Observer(Protocol):
    def on_change(self) -> None: ...


class Subject(Protocol):
    def add(self, observer: Observer) -> None: ...
    def remove(self, observer: Observer) -> None: ...


class Action(Protocol):
    def run(self) -> Result: ...


class Link(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Product:
    link: Link
    input: Input[Slot]
    subject: Subject


class Factory(Protocol):
    def make(self) -> Product: ...

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from .model import Change, Result, Slot


class InputError(RuntimeError):
    pass


class Input[T](Protocol):
    def take(self) -> T | None: ...


class Read[T](Protocol):
    def read(self) -> T: ...


class Observer(Protocol):
    def on_change(self) -> None: ...


class Subject(Protocol):
    def add(self, observer: Observer) -> None: ...
    def remove(self, observer: Observer) -> None: ...


class Button(Read[bool], Input[Change], Subject, Protocol):
    pass


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


@dataclass(frozen=True, slots=True)
class ButtonProduct:
    link: Link
    buttons: Mapping[Slot, Button]

    def __post_init__(self) -> None:
        object.__setattr__(self, "buttons", MappingProxyType(dict(self.buttons)))


class Factory(Protocol):
    def make(self) -> Product: ...


class ButtonFactory(Protocol):
    def make_buttons(self) -> ButtonProduct: ...

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from . import _native as core  # pyright: ignore[reportMissingModuleSource]
from .model import Change, Result, Slot

InputError = core.InputError


class Input[T](ABC):
    @abstractmethod
    def take(self) -> T | None: ...


class Read[T](ABC):
    @abstractmethod
    def read(self) -> T: ...


class Observer(ABC):
    @abstractmethod
    def on_change(self) -> None: ...


class Subject(ABC):
    @abstractmethod
    def add(self, observer: Observer, /) -> None: ...

    @abstractmethod
    def remove(self, observer: Observer, /) -> None: ...


class Button(Read[bool], Input[Change], Subject):
    pass


class Action(ABC):
    @abstractmethod
    def run(self) -> Result: ...


class Link(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
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


class Factory(ABC):
    @abstractmethod
    def make(self) -> Product: ...


class ButtonFactory(ABC):
    @abstractmethod
    def make_buttons(self) -> ButtonProduct: ...


def read_view[T](state: Read[T]) -> Read[T]:
    return cast(Read[T], core.read_view(state))


def input_view[T](input: Input[T]) -> Input[T]:
    return cast(Input[T], core.input_view(input))


def subject_view(subject: Subject) -> Subject:
    return core.subject_view(subject)


Button.register(core.Button)
Read.register(core.ReadView)
Input.register(core.InputView)
Subject.register(core.SubjectView)

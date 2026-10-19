from collections.abc import Mapping
from dataclasses import dataclass

from . import _native as core  # pyright: ignore[reportMissingModuleSource]
from .model import Slot
from .ports import Action


@dataclass(frozen=True, slots=True, init=False)
class Binding:
    _native: core.Binding

    def __init__(self, actions: Mapping[Slot, Action]) -> None:
        object.__setattr__(self, "_native", core.Binding(dict(actions)))

    def select(self, slot: Slot) -> Action | None:
        return self._native.select(slot)

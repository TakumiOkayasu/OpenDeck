from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .model import Slot
from .ports import Action


@dataclass(frozen=True, slots=True, init=False)
class Binding:
    _actions: Mapping[Slot, Action]

    def __init__(self, actions: Mapping[Slot, Action]) -> None:
        object.__setattr__(self, "_actions", MappingProxyType(dict(actions)))

    def select(self, slot: Slot) -> Action | None:
        return self._actions.get(slot)

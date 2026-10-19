from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

Slot = NewType("Slot", str)


@dataclass(frozen=True, slots=True)
class Change:
    pressed: bool
    at: float


@dataclass(frozen=True, slots=True)
class Chord:
    members: frozenset[Slot]
    slot: Slot

    def __post_init__(self) -> None:
        object.__setattr__(self, "members", frozenset(self.members))
        if len(self.members) < 2:
            raise ValueError("A chord needs at least two input slots")


class Status(StrEnum):
    DONE = "done"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Result:
    status: Status
    detail: str = ""

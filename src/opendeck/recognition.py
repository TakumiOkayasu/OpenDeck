from collections.abc import Iterable
from dataclasses import dataclass, field

from . import _native as core  # pyright: ignore[reportMissingModuleSource]
from .model import Chord, Slot


def _definitions(chords: tuple[Chord, ...]) -> tuple[tuple[frozenset[Slot], Slot], ...]:
    return tuple((chord.members, chord.slot) for chord in chords)


def validate_adaptation(slots: Iterable[Slot], chords: tuple[Chord, ...]) -> None:
    core.validate_adaptation(tuple(slots), _definitions(chords))


@dataclass(frozen=True, slots=True)
class State:
    held: frozenset[Slot] = field(default_factory=frozenset)
    claimed: frozenset[Slot] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "held", frozenset(self.held))
        object.__setattr__(self, "claimed", frozenset(self.claimed))
        core.validate_state(self.held, self.claimed)


def apply(
    state: State,
    slot: Slot,
    pressed: bool,
    chords: tuple[Chord, ...] = (),
) -> tuple[State, tuple[Slot, ...]]:
    held, claimed, slots = core.apply(
        state.held, state.claimed, slot, pressed, _definitions(chords)
    )
    return State(held, claimed), slots


def hold(
    held: frozenset[Slot],
    slot: Slot,
    pressed: bool,
    chords: tuple[Chord, ...] = (),
) -> tuple[frozenset[Slot], frozenset[Slot]]:
    return core.hold(held, slot, pressed, _definitions(chords))

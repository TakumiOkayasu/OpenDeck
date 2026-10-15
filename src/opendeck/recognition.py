from collections.abc import Iterable
from dataclasses import dataclass, field

from .model import Chord, Slot


def validate_adaptation(slots: Iterable[Slot], chords: tuple[Chord, ...]) -> None:
    inputs = tuple(slots)
    available = frozenset(inputs)
    if len(available) != len(inputs):
        raise ValueError("Each physical input must adapt to a distinct base slot")
    if any(not chord.members <= available for chord in chords):
        raise ValueError("Chord members must all be adapted base slots")


@dataclass(frozen=True, slots=True)
class State:
    held: frozenset[Slot] = field(default_factory=frozenset)
    claimed: frozenset[Slot] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "held", frozenset(self.held))
        object.__setattr__(self, "claimed", frozenset(self.claimed))
        if not self.claimed <= self.held:
            raise ValueError("Claimed input slots must still be held")


def apply(
    state: State,
    slot: Slot,
    pressed: bool,
    chords: tuple[Chord, ...] = (),
) -> tuple[State, tuple[Slot, ...]]:
    if pressed:
        if slot in state.held:
            return state, ()
        return State(state.held | {slot}, state.claimed), ()
    if slot not in state.held:
        return state, ()

    held = state.held - {slot}
    if slot in state.claimed:
        return State(held, state.claimed - {slot}), ()

    available = state.held - state.claimed
    candidates = (
        chord
        for chord in chords
        if slot in chord.members and chord.members <= available
    )
    chord = max(candidates, key=lambda candidate: len(candidate.members), default=None)
    if chord is None:
        return State(held, state.claimed), (slot,)
    return State(held, state.claimed | (chord.members - {slot})), (chord.slot,)

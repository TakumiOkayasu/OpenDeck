import pytest

from opendeck.model import Chord, Slot
from opendeck.recognition import State, apply, validate_adaptation

A = Slot("a")
B = Slot("b")
C = Slot("c")
AB = Slot("ab")
AC = Slot("ac")
ABC = Slot("abc")


def recognize(
    edges: tuple[tuple[Slot, bool], ...], chords: tuple[Chord, ...] = ()
) -> tuple[State, tuple[Slot, ...]]:
    state = State()
    emitted: tuple[Slot, ...] = ()
    for slot, pressed in edges:
        state, signals = apply(state, slot, pressed, chords)
        emitted += signals
    return state, emitted


def test_single_inputs_emit_on_release_and_repeat() -> None:
    state, signals = recognize(((A, True), (A, False), (A, True), (A, False)))
    assert signals == (A, A)
    assert state == State()


@pytest.mark.parametrize("first_release", [A, B])
def test_a_chord_suppresses_all_member_singles(first_release: Slot) -> None:
    second_release = B if first_release == A else A
    chord = Chord(frozenset({A, B}), AB)
    state, signals = recognize(
        ((A, True), (B, True), (first_release, False), (second_release, False)),
        (chord,),
    )
    assert signals == (AB,)
    assert state == State()


def test_larger_chord_wins_independent_of_definition_order() -> None:
    small = Chord(frozenset({A, B}), AB)
    large = Chord(frozenset({A, B, C}), ABC)
    edges = ((A, True), (B, True), (C, True), (B, False), (A, False), (C, False))
    assert recognize(edges, (small, large)) == (State(), (ABC,))
    assert recognize(edges, (large, small)) == (State(), (ABC,))


def test_overlapping_equal_sized_chords_use_definition_order() -> None:
    ab = Chord(frozenset({A, B}), AB)
    ac = Chord(frozenset({A, C}), AC)
    edges = ((A, True), (B, True), (C, True), (A, False), (B, False), (C, False))
    assert recognize(edges, (ab, ac)) == (State(), (AB, C))
    assert recognize(edges, (ac, ab)) == (State(), (AC, B))


def test_an_already_claimed_member_cannot_trigger_a_second_chord() -> None:
    ab = Chord(frozenset({A, B}), AB)
    bc = Chord(frozenset({B, C}), Slot("bc"))
    edges = ((A, True), (B, True), (A, False), (C, True), (C, False), (B, False))
    assert recognize(edges, (ab, bc)) == (State(), (AB, C))


def test_released_member_can_be_used_in_a_new_chord() -> None:
    ab = Chord(frozenset({A, B}), AB)
    ac = Chord(frozenset({A, C}), AC)
    edges = (
        (A, True),
        (B, True),
        (A, False),
        (A, True),
        (C, True),
        (C, False),
        (A, False),
        (B, False),
    )
    assert recognize(edges, (ab, ac)) == (State(), (AB, AC))


def test_duplicate_edges_do_not_repeat_a_signal() -> None:
    edges = ((A, False), (A, True), (A, True), (A, False), (A, False))
    assert recognize(edges) == (State(), (A,))


def test_recognition_keeps_prior_state_unchanged() -> None:
    state = State(frozenset({A, B}))
    chord = Chord(frozenset({A, B}), AB)
    first = apply(state, A, False, (chord,))
    second = apply(state, A, False, (chord,))
    assert first == second
    assert state == State(frozenset({A, B}))


def test_invalid_recognition_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least two"):
        Chord(frozenset(), AB)
    with pytest.raises(ValueError, match="at least two"):
        Chord(frozenset({A}), AB)
    with pytest.raises(ValueError, match="still be held"):
        State(frozenset({A}), frozenset({B}))


def test_a_chord_can_repeat_after_all_members_are_released() -> None:
    chord = Chord(frozenset({A, B}), AB)
    edges = ((A, True), (B, True), (A, False), (B, False))
    assert recognize(edges + edges, (chord,)) == (State(), (AB, AB))


def test_an_unrelated_release_does_not_activate_a_held_chord() -> None:
    chord = Chord(frozenset({A, B}), AB)
    edges = ((A, True), (B, True), (C, True), (C, False), (A, False), (B, False))
    assert recognize(edges, (chord,)) == (State(), (C, AB))


def test_adaptation_accepts_distinct_inputs_and_available_chord_members() -> None:
    chord = Chord(frozenset({A, B}), AB)
    assert validate_adaptation((A, B, C), (chord,)) is None


def test_adaptation_rejects_multiple_inputs_with_the_same_base_slot() -> None:
    with pytest.raises(ValueError, match="distinct base slot"):
        validate_adaptation((A, A), ())


def test_adaptation_rejects_a_chord_with_an_unavailable_base_slot() -> None:
    chord = Chord(frozenset({A, C}), AC)
    with pytest.raises(ValueError, match="adapted base slots"):
        validate_adaptation((A, B), (chord,))


def test_adaptation_rejects_nested_chord_inputs_unsupported_by_the_recognizer() -> None:
    inner = Chord(frozenset({A, B}), AB)
    outer = Chord(frozenset({AB, C}), ABC)
    with pytest.raises(ValueError, match="adapted base slots"):
        validate_adaptation((A, B, C), (inner, outer))

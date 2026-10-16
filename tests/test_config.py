from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from operator import setitem
from typing import cast

import pytest

from opendeck.config import ConfigError, parse
from opendeck.launch import Launch, LaunchBuilder
from opendeck.model import Result, Slot, Status
from opendeck.ports import Action


class RecordingStart:
    def __init__(self):
        self.calls = []

    def start(self, argv):
        self.calls.append(argv)
        return Result(Status.DONE)


def document():
    return {
        "inputs": ["a", "b", "together"],
        "chords": [{"inputs": ["a", "b"], "slot": "together"}],
        "device": {"keys": {"1": "a", "2": "b"}},
        "actions": {
            "open": {"kind": "launch", "argv": ["app", "argument with spaces"]}
        },
        "bindings": {"a": "open", "together": "open"},
    }


def test_parse_has_no_external_effect_and_snapshot_is_immutable():
    target = RecordingStart()
    data = document()
    settings = parse(data, {"launch": LaunchBuilder(target)})
    data["actions"]["open"]["argv"][0] = "changed"
    data["device"]["keys"]["1"] = "b"
    assert target.calls == []
    assert settings.keys[1] == Slot("a")
    with pytest.raises(TypeError):
        # Exercise runtime immutability despite the read-only static interface.
        setitem(cast(MutableMapping[int, Slot], settings.keys), 1, Slot("b"))
    selected = settings.binding.select(Slot("a"))
    assert selected is not None
    selected.run()
    assert target.calls == [("app", "argument with spaces")]
    assert settings.binding.select(Slot("a")) is settings.binding.select(
        Slot("together")
    )


def test_device_change_preserves_upper_input_definition_and_bindings():
    data = document()
    other = deepcopy(data)
    other["device"]["keys"] = {"8": "a", "12": "b"}
    builders = {"launch": LaunchBuilder(RecordingStart())}
    first, second = parse(data, builders), parse(other, builders)
    assert first.inputs == second.inputs
    assert first.chords == second.chords
    first_action = first.binding.select(Slot("together"))
    second_action = second.binding.select(Slot("together"))
    assert isinstance(first_action, Launch)
    assert isinstance(second_action, Launch)
    assert first_action.argv == second_action.argv


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("inputs", ["a", "a"]),
        ("bindings", {"unknown": "open"}),
        ("bindings", {"a": "unknown"}),
        ("chords", [{"inputs": ["a"], "slot": "together"}]),
        ("chords", [{"inputs": ["a", "missing"], "slot": "together"}]),
        ("chords", [{"inputs": ["a", "b"], "slot": "a"}]),
        ("actions", {"open": {"kind": "unknown", "argv": ["app"]}}),
        ("actions", {"open": {"kind": "launch", "argv": []}}),
        ("actions", {"open": {"kind": "launch", "argv": ["app\0"]}}),
        ("device", {"keys": {"01": "a"}}),
        ("device", {"keys": {"-1": "a"}}),
        ("device", {"keys": {"1": "missing"}}),
    ],
)
def test_invalid_configuration_is_rejected_before_operations(section, value):
    data = document()
    data[section] = value
    target = RecordingStart()
    with pytest.raises(ConfigError):
        parse(data, {"launch": LaunchBuilder(target)})
    assert target.calls == []


def test_unknown_fields_are_rejected_instead_of_silently_ignored():
    data = document()
    data["actions"]["open"]["admin"] = True
    with pytest.raises(ConfigError, match=r"actions\[open\]: .*unknown=.*admin"):
        parse(data, {"launch": LaunchBuilder(RecordingStart())})


@pytest.mark.parametrize(
    "definition",
    [
        None,
        [],
        {},
        {"kind": None},
        {"kind": True},
        {"kind": 1},
        {"kind": []},
        {"kind": {}},
        {"kind": ""},
        {"kind": "   "},
    ],
)
def test_invalid_action_definition_is_rejected_before_building(definition):
    def build(options: Mapping[str, object]) -> Action:
        pytest.fail("invalid definitions must be rejected before calling a builder")

    data = document()
    data["actions"]["open"] = definition
    with pytest.raises(ConfigError, match=r"actions\[open\]"):
        parse(data, {"launch": build})


@pytest.mark.parametrize("kind", ["launch", "unregistered"])
def test_no_implicit_action_registration(kind):
    data = document()
    data["actions"]["open"]["kind"] = kind
    with pytest.raises(ConfigError, match=rf"actions\[open\]: unknown kind '{kind}'"):
        parse(data, {})


def test_no_action_registration_is_needed_for_empty_actions():
    data = document()
    data["actions"] = {}
    data["bindings"] = {}
    settings = parse(data, {})
    assert all(settings.binding.select(slot) is None for slot in settings.inputs)


def test_builder_validation_error_preserves_location_and_cause():
    error = ValueError("invalid custom setting")

    def build(options: Mapping[str, object]) -> Action:
        assert options == {"value": 42}
        raise error

    data = document()
    data["actions"]["open"] = {"kind": "custom", "value": 42}
    with pytest.raises(
        ConfigError, match=r"actions\[open\]: invalid custom setting"
    ) as caught:
        parse(data, {"custom": build})
    assert caught.value.__cause__ is error


@pytest.mark.parametrize("error", [TypeError("bug"), RuntimeError("bug")])
def test_builder_implementation_errors_are_not_reclassified(error):
    def build(options: Mapping[str, object]) -> Action:
        raise error

    with pytest.raises(type(error)) as caught:
        parse(document(), {"launch": build})
    assert caught.value is error

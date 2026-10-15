from copy import deepcopy

import pytest

from opendeck.config import ConfigError, parse
from opendeck.model import Result, Slot, Status


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
    settings = parse(data, target)
    data["actions"]["open"]["argv"][0] = "changed"
    data["device"]["keys"]["1"] = "b"
    assert target.calls == []
    assert settings.keys[1] == Slot("a")
    with pytest.raises(TypeError):
        settings.keys[1] = Slot("b")
    settings.binding.select(Slot("a")).run()
    assert target.calls == [("app", "argument with spaces")]
    assert settings.binding.select(Slot("a")) is settings.binding.select(
        Slot("together")
    )


def test_device_change_preserves_upper_input_definition_and_bindings():
    data = document()
    other = deepcopy(data)
    other["device"]["keys"] = {"8": "a", "12": "b"}
    first, second = parse(data, RecordingStart()), parse(other, RecordingStart())
    assert first.inputs == second.inputs
    assert first.chords == second.chords
    assert first.binding.select(Slot("together")).argv == (
        second.binding.select(Slot("together")).argv
    )


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
        parse(data, target)
    assert target.calls == []


def test_unknown_fields_are_rejected_instead_of_silently_ignored():
    data = document()
    data["actions"]["open"]["admin"] = True
    with pytest.raises(ConfigError, match="unknown=.*admin"):
        parse(data, RecordingStart())

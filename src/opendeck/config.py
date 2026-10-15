from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from .bindings import Binding
from .launch import Launch, Start
from .model import Chord, Slot
from .ports import Action


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    inputs: tuple[Slot, ...]
    chords: tuple[Chord, ...]
    keys: Mapping[int, Slot]
    binding: Binding


def _record(value: object, required: set[str], location: str) -> dict[str, object]:
    record = _mapping(value, location)
    keys = set(record)
    if keys != required:
        raise ConfigError(
            f"{location}: missing={sorted(required - keys)}, "
            f"unknown={sorted(keys - required)}"
        )
    return record


def _mapping(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigError(f"{location}: expected an object")
    return cast(dict[str, object], value)


def _names(value: object, location: str) -> tuple[Slot, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{location}: expected a nonempty list")
    if any(not isinstance(name, str) or not name.strip() for name in value):
        raise ConfigError(f"{location}: input names must be nonempty strings")
    if len(set(value)) != len(value):
        raise ConfigError(f"{location}: duplicate input")
    return tuple(Slot(name) for name in value)


def _slot(value: object, inputs: tuple[Slot, ...], location: str) -> Slot:
    if not isinstance(value, str) or value not in inputs:
        raise ConfigError(f"{location}: unknown input {value!r}")
    return Slot(value)


def _chords(value: object, inputs: tuple[Slot, ...]) -> tuple[Chord, ...]:
    if not isinstance(value, list):
        raise ConfigError("chords: expected a list")
    result: list[Chord] = []
    seen: set[frozenset[Slot]] = set()
    for index, item in enumerate(value):
        location = f"chords[{index}]"
        record = _record(item, {"inputs", "slot"}, location)
        members = frozenset(
            _slot(name, inputs, location) for name in _names(record["inputs"], location)
        )
        slot = _slot(record["slot"], inputs, location)
        if len(members) < 2 or slot in members or members in seen:
            raise ConfigError(f"{location}: invalid or duplicate combination")
        result.append(Chord(members, slot))
        seen.add(members)
    return tuple(result)


def _keys(value: object, inputs: tuple[Slot, ...]) -> Mapping[int, Slot]:
    result: dict[int, Slot] = {}
    for key, name in _mapping(value, "device.keys").items():
        try:
            number = int(key)
        except ValueError as error:
            raise ConfigError(f"device.keys: invalid identifier {key!r}") from error
        if number <= 0 or str(number) != key:
            raise ConfigError(f"device.keys: invalid identifier {key!r}")
        result[number] = _slot(name, inputs, f"device.keys[{key}]")
    return MappingProxyType(result)


def _actions(value: object, target: Start) -> Mapping[str, Action]:
    result: dict[str, Action] = {}
    for name, definition in _mapping(value, "actions").items():
        if not name.strip():
            raise ConfigError("actions: action names must be nonempty")
        record = _record(definition, {"kind", "argv"}, f"actions[{name}]")
        if record["kind"] != "launch":
            raise ConfigError(f"actions[{name}]: unknown kind {record['kind']!r}")
        argv = record["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
            or not argv[0]
        ):
            raise ConfigError(f"actions[{name}]: expected a nonempty argument list")
        result[name] = Launch(tuple(argv), target)
    return MappingProxyType(result)


def parse(value: object, target: Start) -> Settings:
    record = _record(
        value, {"inputs", "chords", "device", "actions", "bindings"}, "config"
    )
    inputs = _names(record["inputs"], "inputs")
    chords = _chords(record["chords"], inputs)
    device = _record(record["device"], {"keys"}, "device")
    keys = _keys(device["keys"], inputs)
    actions = _actions(record["actions"], target)
    mapping: dict[Slot, Action] = {}
    for name, value in _mapping(record["bindings"], "bindings").items():
        slot = _slot(name, inputs, "bindings")
        if not isinstance(value, str) or value not in actions:
            raise ConfigError(f"bindings[{name}]: unknown action {value!r}")
        mapping[slot] = actions[value]
    return Settings(inputs, chords, keys, Binding(mapping))

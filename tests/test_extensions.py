import json
import subprocess
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from operator import setitem
from typing import cast

import pytest

from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.cli import _execute
from opendeck.config import Builder, parse
from opendeck.launch import LaunchBuilder
from opendeck.model import Result, Slot, Status
from opendeck.ports import Action
from opendeck.runtime import drain


@pytest.mark.parametrize("status", [Status.DONE, Status.FAILED, Status.UNKNOWN])
def test_registered_action_uses_existing_input_binding_and_execution(status: Status):
    calls: list[str] = []
    starts: list[tuple[str, ...]] = []
    built: list[Mapping[str, object]] = []

    @dataclass(frozen=True)
    class Message:
        text: str

        def run(self) -> Result:
            calls.append(self.text)
            return Result(status, self.text)

    def build_message(options: Mapping[str, object]) -> Action:
        assert options == {"text": "recorded"}
        with pytest.raises(TypeError):
            setitem(cast(MutableMapping[str, object], options), "text", "changed")
        text = options["text"]
        if not isinstance(text, str):
            raise ValueError("expected text")
        built.append(options)
        return Message(text)

    class Target:
        def start(self, argv: tuple[str, ...]) -> Result:
            starts.append(argv)
            return Result(Status.DONE)

    builders: dict[str, Builder] = {
        "launch": LaunchBuilder(Target()),
        "message": build_message,
    }
    settings = parse(
        {
            "inputs": ["single", "other", "combined", "unassigned"],
            "chords": [{"inputs": ["single", "other"], "slot": "combined"}],
            "device": {"keys": {"1": "single", "2": "other", "3": "unassigned"}},
            "actions": {
                "app": {"kind": "launch", "argv": ["app", "argument with spaces"]},
                "notice": {"kind": "message", "text": "recorded"},
            },
            "bindings": {"single": "notice", "combined": "notice", "other": "app"},
        },
        builders,
    )
    assert len(built) == 1
    assert calls == starts == []
    assert settings.binding.select(Slot("single")) is settings.binding.select(
        Slot("combined")
    )
    # Registrations are needed only to construct actions, not to execute them.
    builders.clear()
    product = ReplayFactory(
        settings.keys,
        settings.chords,
        (
            Edge(1, True),
            Edge(1, False),
            Edge(2, True),
            Edge(2, False),
            Edge(1, True),
            Edge(2, True),
            Edge(1, False),
            Edge(2, False),
            Edge(3, True),
            Edge(3, False),
            Edge(1, True),
            Edge(1, False),
        ),
    ).make()
    results: list[tuple[Slot, Result | None]] = []
    try:
        product.link.open()
        assert calls == starts == []
        assert (
            drain(product.input, settings.binding, lambda *args: results.append(args))
            == 5
        )
        assert product.input.take() is None
    finally:
        product.link.close()
    assert len(built) == 1
    assert calls == ["recorded", "recorded", "recorded"]
    assert starts == [("app", "argument with spaces")]
    assert results == [
        (Slot("single"), Result(status, "recorded")),
        (Slot("other"), Result(Status.DONE)),
        (Slot("combined"), Result(status, "recorded")),
        (Slot("unassigned"), None),
        (Slot("single"), Result(status, "recorded")),
    ]


def test_same_kind_builds_each_definition_once_including_unbound_actions():
    built: list[Action] = []

    @dataclass(frozen=True)
    class NamedAction:
        name: str

        def run(self) -> Result:
            pytest.fail("configuration must not execute actions")

    def build(options: Mapping[str, object]) -> Action:
        name = options["name"]
        if not isinstance(name, str):
            raise ValueError("expected a name")
        action = NamedAction(name)
        built.append(action)
        return action

    settings = parse(
        {
            "inputs": ["a", "b", "repeat", "missing"],
            "chords": [],
            "device": {"keys": {}},
            "actions": {
                "first": {"kind": "named", "name": "one"},
                "second": {"kind": "named", "name": "two"},
                "unbound": {"kind": "named", "name": "unused"},
            },
            "bindings": {"a": "first", "b": "second", "repeat": "first"},
        },
        {"named": build},
    )
    assert built == [NamedAction("one"), NamedAction("two"), NamedAction("unused")]
    assert settings.binding.select(Slot("a")) is built[0]
    assert settings.binding.select(Slot("b")) is built[1]
    assert settings.binding.select(Slot("repeat")) is built[0]
    assert settings.binding.select(Slot("missing")) is None


@pytest.mark.parametrize("first", [Status.FAILED, Status.UNKNOWN])
def test_cli_reports_each_result_and_retains_failure_after_later_success(
    first: Status, capsys: pytest.CaptureFixture[str]
):
    expected = [
        Result(status, f"run {index}")
        for index, status in enumerate(
            (first, Status.DONE, Status.UNKNOWN, Status.DONE)
        )
    ]
    results = iter(expected)
    calls: list[Result] = []

    class ChangingAction:
        def run(self) -> Result:
            result = next(results)
            calls.append(result)
            return result

    def build(options: Mapping[str, object]) -> Action:
        assert not options
        return ChangingAction()

    settings = parse(
        {
            "inputs": ["trigger"],
            "chords": [],
            "device": {"keys": {"1": "trigger"}},
            "actions": {"changing": {"kind": "changing"}},
            "bindings": {"trigger": "changing"},
        },
        {"changing": build},
    )
    product = ReplayFactory(
        settings.keys,
        settings.chords,
        (Edge(1, True), Edge(1, False)) * len(expected),
    ).make()
    assert _execute(product, settings.binding, False) == 1
    assert calls == expected
    output = capsys.readouterr()
    assert output.err == ""
    assert [json.loads(line) for line in output.out.splitlines()] == [
        {"input": "trigger", "status": result.status.value, "detail": result.detail}
        for result in expected
    ]


def test_common_configuration_import_does_not_load_features_or_native_sdk():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "from opendeck.config import parse\n"
            "parse({'inputs': ['a'], 'chords': [], 'device': {'keys': {}}, "
            "'actions': {}, 'bindings': {}}, {})\n"
            "assert 'opendeck.launch' not in sys.modules\n"
            "assert not any(name.startswith(('opendeck.adapters', 'StreamDock')) "
            "for name in sys.modules)\n",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr

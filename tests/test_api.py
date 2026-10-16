import subprocess
import sys
from pathlib import Path

import pytest

from opendeck import (
    Action,
    Binding,
    Chord,
    Input,
    InputError,
    Observer,
    Result,
    Slot,
    Status,
    Subject,
)
from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.source import Source


def test_application_receives_virtual_keys_through_public_input_contract():
    primary, secondary = Slot("primary"), Slot("secondary")
    pending = iter((primary, secondary, primary))

    class Provider:
        def take(self) -> Slot | None:
            return next(pending, None)

    def receive(input: Input[Slot]) -> list[Slot]:
        received: list[Slot] = []
        while (slot := input.take()) is not None:
            received.append(slot)
        return received

    assert receive(Provider()) == [primary, secondary, primary]


def test_application_changes_key_configuration_without_changing_adaptation():
    primary = Slot("primary")
    calls: list[str] = []

    class Operation:
        def __init__(self, name: str) -> None:
            self.name = name

        def run(self) -> Result:
            calls.append(self.name)
            return Result(Status.DONE)

    def execute(input: Input[Slot], binding: Binding) -> Result:
        slot = input.take()
        assert slot is not None
        action = binding.select(slot)
        assert action is not None
        return action.run()

    original: Action = Operation("original")
    replacement: Action = Operation("replacement")
    factory = ReplayFactory({1: primary}, (), (Edge(1, True), Edge(1, False)))
    for action in (original, replacement):
        product = factory.make()
        try:
            product.link.open()
            assert execute(product.input, Binding({primary: action})) == Result(
                Status.DONE
            )
            assert product.input.take() is None
        finally:
            product.link.close()
    assert calls == ["original", "replacement"]


def test_application_distinguishes_input_failure_from_empty_input():
    def receive(input: Input[Slot]) -> Slot | None:
        return input.take()

    source = Source[Slot]()
    source.start()
    try:
        assert receive(source) is None
        source.fail("disconnected")
        with pytest.raises(InputError, match="disconnected"):
            receive(source)
    finally:
        source.close()


def test_application_observes_chord_input_without_physical_state():
    primary, secondary, together = (
        Slot("primary"),
        Slot("secondary"),
        Slot("together"),
    )
    chord = Chord(frozenset({primary, secondary}), together)
    notifications: list[None] = []

    class Listener:
        def on_change(self) -> None:
            notifications.append(None)

    def subscribe(subject: Subject, observer: Observer) -> None:
        subject.add(observer)

    product = ReplayFactory(
        {1: primary, 2: secondary},
        (chord,),
        (Edge(1, True), Edge(2, True), Edge(1, False), Edge(2, False)),
    ).make()
    listener = Listener()
    subscribe(product.subject, listener)
    try:
        product.link.open()
        assert notifications
        assert product.input.take() == together
        assert product.input.take() is None
    finally:
        product.link.close()
        product.subject.remove(listener)


def test_generic_input_is_not_fixed_to_virtual_keys_or_numeric_values():
    class Reader:
        def take(self) -> tuple[str, bool]:
            return ("available", True)

    input: Input[tuple[str, bool]] = Reader()
    assert input.take() == ("available", True)


def test_public_contract_import_does_not_load_implementations_or_sdk():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "from opendeck import (Action, Binding, Chord, Input, InputError, "
            "Observer, Result, Slot, Status, Subject)\n"
            "assert not any(name.startswith(('opendeck.adapters', 'StreamDock')) "
            "for name in sys.modules)\n"
            "assert not {'opendeck.cli', 'opendeck.config', 'opendeck.launch', "
            "'opendeck.source', 'opendeck.recognition'} & sys.modules.keys()\n",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_extension_example_runs_without_sdk_or_launching_applications():
    example = Path(__file__).resolve().parents[1] / "examples" / "extension.py"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys\n"
            "def guard(event, args):\n"
            "    if event == 'subprocess.Popen':\n"
            "        raise AssertionError('example must not launch applications')\n"
            "    if event == 'import' and args[0].startswith('StreamDock'):\n"
            "        raise AssertionError('example must not import the SDK')\n"
            "sys.addaudithook(guard)\n"
            "runpy.run_path(sys.argv[1], run_name='__main__')\n",
            str(example),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["primary: done", "recorded by extension"]
    assert result.stderr == ""

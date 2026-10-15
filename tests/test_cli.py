import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress

import pytest

from opendeck.bindings import Binding
from opendeck.cli import _execute, main
from opendeck.model import Result, Slot, Status
from opendeck.ports import Product
from opendeck.source import Source


def files(tmp_path, argv):
    config = tmp_path / "config.json"
    events = tmp_path / "events.json"
    config.write_text(
        json.dumps(
            {
                "inputs": ["a", "b", "together"],
                "chords": [{"inputs": ["a", "b"], "slot": "together"}],
                "device": {"keys": {"1": "a", "2": "b"}},
                "actions": {"start": {"kind": "launch", "argv": argv}},
                "bindings": {"together": "start"},
            }
        ),
        encoding="utf-8",
    )
    events.write_text(
        json.dumps(
            [
                {"key": 1, "pressed": True},
                {"key": 2, "pressed": True},
                {"key": 1, "pressed": False},
                {"key": 2, "pressed": False},
            ]
        ),
        encoding="utf-8",
    )
    return config, events


def test_replay_to_real_process_works_without_importing_native_sdk(tmp_path):
    launched = tmp_path / "result.txt"
    argv = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('started')",
        str(launched),
    ]
    config, events = files(tmp_path, argv)
    result = subprocess.run(
        [sys.executable, "-m", "opendeck", "replay", str(config), str(events)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    reports = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(reports) == 1
    assert reports[0]["input"] == "together"
    assert reports[0]["status"] == "done"
    deadline = time.monotonic() + 5
    content = ""
    while time.monotonic() < deadline:
        if launched.exists():
            content = launched.read_text()
            if content == "started":
                break
        time.sleep(0.01)
    assert content == "started"


def test_child_stdio_does_not_contaminate_cli_reports(tmp_path):
    config, events = files(tmp_path, [sys.executable, "-c", "print('child-output')"])
    result = subprocess.run(
        [sys.executable, "-m", "opendeck", "replay", str(config), str(events)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert len(result.stdout.splitlines()) == 1
    assert json.loads(result.stdout)["status"] == "done"
    assert "child-output" not in result.stderr


def test_replay_launch_failure_sets_nonzero_status(tmp_path, capsys):
    config, events = files(tmp_path, [str(tmp_path / "missing-program")])
    assert main(["replay", str(config), str(events)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_malformed_events_fail_without_execution(tmp_path, capsys):
    config, events = files(tmp_path, [str(tmp_path / "missing-program")])
    events.write_text('[{"key": 1, "pressed": 1}]', encoding="utf-8")
    assert main(["replay", str(config), str(events)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "events[0]" in output.err


def test_cleanup_occurs_after_open_failure():
    source = Source[Slot]()
    calls = []

    class Link:
        def open(self):
            calls.append("open")
            raise ConnectionError("failed")

        def close(self):
            calls.append("close")

    with pytest.raises(ConnectionError):
        _execute(Product(Link(), source, source), Binding({}), False)
    assert calls == ["open", "close"]
    assert source._observers == []


def test_start_request_returns_without_waiting_for_child_exit(tmp_path):
    pid_file = tmp_path / "pid"
    script = (
        "import os, sys, time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    config, events = files(tmp_path, [sys.executable, "-c", script, str(pid_file)])
    try:
        result = subprocess.run(
            [sys.executable, "-m", "opendeck", "replay", str(config), str(events)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout)["status"] == "done"
    finally:
        deadline = time.monotonic() + 5
        pid = None
        while time.monotonic() < deadline:
            if pid_file.exists():
                content = pid_file.read_text()
                if content.isdigit():
                    pid = int(content)
                    break
            time.sleep(0.01)
        if pid is not None:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)


def test_keyboard_interrupt_preserves_previous_operation_failure():
    source = Source[Slot]()
    slot = Slot("failed")

    class Link:
        def open(self):
            source.start()
            source.publish(slot)

        def close(self):
            source.close()

    class Action:
        def run(self):
            return Result(Status.FAILED)

    class Input:
        def take(self):
            value = source.take()
            if value is None:
                raise KeyboardInterrupt
            return value

    assert (
        _execute(Product(Link(), Input(), source), Binding({slot: Action()}), True) == 1
    )


def test_startup_and_cleanup_errors_are_both_preserved():
    source = Source[Slot]()

    class Link:
        def open(self):
            raise ConnectionError("startup failed")

        def close(self):
            raise RuntimeError("cleanup failed")

    with pytest.raises(ExceptionGroup) as captured:
        _execute(Product(Link(), source, source), Binding({}), False)
    assert [str(error) for error in captured.value.exceptions] == [
        "startup failed",
        "cleanup failed",
    ]
    assert source._observers == []

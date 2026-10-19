import json
import logging
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from io import StringIO
from pathlib import Path

import pytest

from opendeck.adapters import streamdock
from opendeck.bindings import Binding
from opendeck.cli import _execute, main
from opendeck.model import Result, Slot, Status
from opendeck.ports import Product
from opendeck.source import Source


class TrackedSource(Source[Slot]):
    def __init__(self):
        super().__init__()
        self.attached = []

    def add(self, observer):
        super().add(observer)
        self.attached.append(observer)

    def remove(self, observer):
        super().remove(observer)
        self.attached.remove(observer)


def files(tmp_path: Path, argv: list[str]) -> tuple[Path, Path]:
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
    source = TrackedSource()
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
    assert source.attached == []


@pytest.mark.parametrize("failure", [None, "factory", "open", "input", "close"])
def test_run_debug_logging_is_temporary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    config, _ = files(tmp_path, [str(tmp_path / "unused-program")])
    source = TrackedSource()
    adapter_logger = logging.getLogger(streamdock.__name__)

    class Link:
        def open(self) -> None:
            adapter_logger.debug("startup")
            if failure == "open":
                raise RuntimeError("open failed")
            source.start()
            adapter_logger.debug("raw event")
            adapter_logger.debug("decoded input")
            source.publish(Slot("a"))

        def close(self) -> None:
            adapter_logger.debug("cleanup")
            source.close()
            if failure == "close":
                raise RuntimeError("close failed")

    class Input:
        def take(self) -> Slot | None:
            value = source.take()
            if value is None:
                if failure == "input":
                    raise RuntimeError("input failed")
                raise KeyboardInterrupt
            return value

    class Factory:
        def __init__(self, *_args: object) -> None:
            pass

        def make(self) -> Product:
            adapter_logger.debug("factory")
            if failure == "factory":
                raise RuntimeError("factory failed")
            return Product(Link(), Input(), source)

    monkeypatch.setattr(streamdock, "StreamDockFactory", Factory)
    logger = logging.getLogger("opendeck")
    level, handlers, propagate = logger.level, logger.handlers[:], logger.propagate
    root = logging.getLogger()
    root_state = root.level, root.handlers[:], root.propagate
    existing_handler = logging.StreamHandler(sys.stdout)
    try:
        logger.setLevel(logging.WARNING)
        logger.handlers = [existing_handler]
        logger.propagate = True
        for debug in (True, False, True):
            argv = ["run", str(config)]
            if debug:
                argv.append("--debug")
            assert main(argv) == (0 if failure is None else 1)
            output = capsys.readouterr()
            if failure in {"factory", "open"}:
                assert output.out == ""
            else:
                assert json.loads(output.out) == {
                    "input": "a",
                    "status": "unassigned",
                    "detail": "",
                }
            reached = {"factory"}
            if failure != "factory":
                reached.update({"startup", "cleanup"})
                if failure != "open":
                    reached.update({"raw event", "decoded input"})
            for event in (
                "factory",
                "startup",
                "raw event",
                "decoded input",
                "cleanup",
            ):
                assert output.err.count(f"opendeck: DEBUG: {event}\n") == int(
                    debug and event in reached
                )
            assert ("Waiting for N4 Pro input" in output.err) is (
                failure not in {"factory", "open"}
            )
            if failure is not None:
                assert f"opendeck: {failure} failed\n" in output.err
            assert logger.level == logging.WARNING
            assert logger.handlers == [existing_handler]
            assert logger.propagate is True
            assert (root.level, root.handlers, root.propagate) == root_state
            assert source.attached == []
    finally:
        logger.setLevel(level)
        logger.handlers = handlers
        logger.propagate = propagate
        existing_handler.close()


@pytest.mark.parametrize(
    "argv",
    [["devices", "--debug"], ["replay", "config.json", "events.json", "--debug"]],
)
def test_debug_flag_is_run_only(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as captured:
        main(argv)
    assert captured.value.code == 2


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_readiness_is_flushed_only_after_successful_live_open(
    monkeypatch: pytest.MonkeyPatch, live: bool, failed: bool
) -> None:
    class ErrorStream(StringIO):
        flushed = False

        def flush(self) -> None:
            self.flushed = True
            super().flush()

    stderr = ErrorStream()
    monkeypatch.setattr(sys, "stderr", stderr)
    source = TrackedSource()
    calls: list[str] = []
    expected = (
        "opendeck: Waiting for N4 Pro input; press Ctrl+C to exit.\n"
        if live and not failed
        else ""
    )

    class Link:
        def open(self) -> None:
            calls.append("open")
            assert stderr.getvalue() == ""
            assert not stderr.flushed
            if failed:
                raise ConnectionError("startup failed")

        def close(self) -> None:
            calls.append("close")

    class Input:
        def take(self) -> Slot | None:
            assert stderr.getvalue() == expected
            assert stderr.flushed is live
            if live:
                raise KeyboardInterrupt
            return None

    product = Product(Link(), Input(), source)
    if failed:
        with pytest.raises(ConnectionError, match="startup failed"):
            _execute(product, Binding({}), live)
    else:
        assert _execute(product, Binding({}), live) == 0
    assert stderr.getvalue() == expected
    assert stderr.flushed is (live and not failed)
    assert calls == ["open", "close"]
    assert source.attached == []


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
    source = TrackedSource()
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
    source = TrackedSource()

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
    assert source.attached == []

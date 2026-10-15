import subprocess
from types import SimpleNamespace

from opendeck.adapters.process import Processes
from opendeck.launch import Launch
from opendeck.model import Result, Status


def test_launch_uses_injected_target_without_input_information():
    calls = []

    class Target:
        def start(self, argv):
            calls.append(argv)
            return Result(Status.UNKNOWN, "unconfirmed")

    action = Launch(("app", "an argument"), Target())
    assert action.run() == Result(Status.UNKNOWN, "unconfirmed")
    assert calls == [("app", "an argument")]


def test_process_start_preserves_argument_boundaries_and_avoids_shell(monkeypatch):
    calls = []

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(pid=123)

    monkeypatch.setattr("opendeck.adapters.process.subprocess.Popen", popen)
    result = Processes().start(("an executable", "argument with spaces", "literal;&"))
    assert result.status is Status.DONE
    assert calls == [
        (
            ("an executable", "argument with spaces", "literal;&"),
            {
                "shell": False,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            },
        )
    ]


def test_process_start_failure_is_not_success_or_retried(monkeypatch):
    calls = []

    def fail(argv, **kwargs):
        calls.append(argv)
        raise FileNotFoundError("not installed")

    monkeypatch.setattr("opendeck.adapters.process.subprocess.Popen", fail)
    assert Processes().start(("missing",)) == Result(Status.FAILED, "not installed")
    assert calls == [("missing",)]

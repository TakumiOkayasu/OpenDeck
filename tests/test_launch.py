import subprocess
from collections.abc import Mapping
from types import SimpleNamespace

import pytest

from opendeck.adapters.process import Processes
from opendeck.launch import Launch, LaunchBuilder
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


def test_launch_builder_snapshots_arguments_without_calling_target():
    calls: list[tuple[str, ...]] = []

    class Target:
        def start(self, argv: tuple[str, ...]) -> Result:
            calls.append(argv)
            return Result(Status.DONE)

    argv = ["an executable", "argument with spaces", "", "literal;&"]
    action = LaunchBuilder(Target())({"argv": argv})
    argv[0] = "changed"
    assert action.argv == (
        "an executable",
        "argument with spaces",
        "",
        "literal;&",
    )
    assert calls == []
    assert action.run() == Result(Status.DONE)
    assert action.run() == Result(Status.DONE)
    assert calls == [action.argv, action.argv]


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"argv": ["app"], "admin": True},
        {"argv": ["app"], "kind": "launch"},
        {"argv": None},
        {"argv": "app"},
        {"argv": ("app",)},
        {"argv": []},
        {"argv": [""]},
        {"argv": [1]},
        {"argv": ["app", None]},
        {"argv": ["app", "bad\0argument"]},
    ],
)
def test_launch_builder_rejects_invalid_settings_before_target_access(
    options: Mapping[str, object],
):
    class Target:
        def start(self, argv: tuple[str, ...]) -> Result:
            pytest.fail("building must not call the target")

    with pytest.raises(ValueError):
        LaunchBuilder(Target())(options)

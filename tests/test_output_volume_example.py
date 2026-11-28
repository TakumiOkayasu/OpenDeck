import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from opendeck import (
    InputError,
    OutputVolume,
    Result,
    Status,
    VolumeError,
    VolumeFailure,
)
from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.config import ConfigError
from opendeck.ports import Input, Link, Product, Subject
from opendeck.runtime import drain

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "output_volume.py"


@pytest.fixture
def example():
    return runpy.run_path(str(SCRIPT))


def configuration():
    return {
        "inputs": ["quiet", "loud", "mute", "unmute"],
        "chords": [],
        "device": {"keys": {"1": "quiet", "2": "loud", "3": "mute", "4": "unmute"}},
        "actions": {
            "quiet": {"kind": "volume", "level": 0.25},
            "loud": {"kind": "volume", "level": 0.5},
            "mute": {"kind": "mute", "muted": True},
            "unmute": {"kind": "mute", "muted": False},
        },
        "bindings": {name: name for name in ("quiet", "loud", "mute", "unmute")},
    }


def test_replayed_inputs_operate_injected_output_in_order(example):
    output = Mock(spec=OutputVolume)
    settings = example["configure"](configuration(), output)
    assert output.mock_calls == []
    events = tuple(
        edge for key in range(1, 5) for edge in (Edge(key, True), Edge(key, False))
    )
    product = ReplayFactory(settings.keys, settings.chords, events).make()
    results = []
    try:
        product.link.open()
        assert output.mock_calls == []
        assert (
            drain(
                product.input,
                settings.binding,
                lambda _, result: results.append(result),
            )
            == 4
        )
    finally:
        product.link.close()
    assert [(call[0], call.args) for call in output.mock_calls] == [
        ("set_volume", (0.25,)),
        ("set_volume", (0.5,)),
        ("set_mute", (True,)),
        ("set_mute", (False,)),
    ]
    assert results == [Result(Status.DONE)] * 4


@pytest.mark.parametrize(
    "action,argument,operation",
    [("SetVolume", 0.25, "set_volume"), ("SetMute", True, "set_mute")],
)
@pytest.mark.parametrize("reason", list(VolumeFailure))
def test_output_failure_becomes_failed_result(
    example, action, argument, operation, reason
):
    output = Mock(spec=OutputVolume)
    error = VolumeError(reason, "output unavailable")
    getattr(output, operation).side_effect = error
    result = example[action](output, argument).run()
    assert result == Result(Status.FAILED, str(error))
    getattr(output, operation).assert_called_once_with(argument)


@pytest.mark.parametrize(
    "action,argument,operation",
    [("SetVolume", 0.25, "set_volume"), ("SetMute", True, "set_mute")],
)
def test_unexpected_output_exception_reaches_the_owner(
    example, action, argument, operation
):
    output = Mock(spec=OutputVolume)
    getattr(output, operation).side_effect = RuntimeError("unexpected failure")
    with pytest.raises(RuntimeError, match="unexpected failure"):
        example[action](output, argument).run()


@pytest.mark.parametrize(
    "options",
    [
        {"level": True},
        {"level": -0.1},
        {"level": 1.1},
        {"level": float("nan")},
        {"level": "0.5"},
        {},
        {"level": 0.5, "other": 1},
    ],
)
def test_volume_builder_rejects_invalid_configuration_without_io(example, options):
    output = Mock(spec=OutputVolume)
    value = configuration()
    value["actions"]["quiet"] = {"kind": "volume", **options}
    with pytest.raises(ConfigError, match="volume"):
        example["configure"](value, output)
    assert output.mock_calls == []


@pytest.mark.parametrize(
    "options", [{"muted": 1}, {"muted": "false"}, {}, {"muted": False, "other": 1}]
)
def test_mute_builder_rejects_invalid_configuration_without_io(example, options):
    output = Mock(spec=OutputVolume)
    value = configuration()
    value["actions"]["mute"] = {"kind": "mute", **options}
    with pytest.raises(ConfigError, match="mute"):
        example["configure"](value, output)
    assert output.mock_calls == []


def test_default_sample_replays_without_loading_system_or_device_adapters():
    script = (
        "import runpy, sys\n"
        f"sample = runpy.run_path({str(SCRIPT)!r})\n"
        "assert sample['main']([]) == 0\n"
        "assert 'opendeck.adapters.macos_volume' not in sys.modules\n"
        "assert 'opendeck.adapters.windows_volume' not in sys.modules\n"
        "assert 'opendeck.adapters.streamdock' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "SIMULATION: output changes are recorded locally.",
        "volume=0.25",
        "quiet: done",
        "volume=0.50",
        "loud: done",
        "muted=True",
        "mute: done",
        "muted=False",
        "unmute: done",
    ]


@pytest.mark.parametrize(
    "failure", [KeyboardInterrupt(), InputError("device disconnected")]
)
def test_live_dispatch_removes_observer_and_closes_connection(example, failure, capsys):
    calls = []
    output = Mock(spec=OutputVolume)
    settings = example["configure"](configuration(), output)
    link = Mock(spec=Link)
    subject = Mock(spec=Subject)
    input = Mock(spec=Input)
    link.open.side_effect = lambda: calls.append("open")
    subject.add.side_effect = lambda _: calls.append("observe")
    subject.remove.side_effect = lambda _: calls.append("unobserve")
    link.close.side_effect = lambda: calls.append("close")
    input.take.side_effect = failure
    product = Product(link, input, subject)
    if isinstance(failure, KeyboardInterrupt):
        assert example["dispatch"](product, settings, live=True) == 0
    else:
        with pytest.raises(InputError, match="device disconnected"):
            example["dispatch"](product, settings, live=True)
    assert calls == ["observe", "open", "unobserve", "close"]
    assert output.mock_calls == []
    assert capsys.readouterr().out.splitlines()[0] == (
        "INPUT OK. Configured buttons are ready. Ctrl+C ends."
    )


def test_dispatch_reports_output_failure_and_accepts_the_next_input(example, capsys):
    output = Mock(spec=OutputVolume)
    output.set_volume.side_effect = VolumeError(VolumeFailure.UNSUPPORTED)
    settings = example["configure"](configuration(), output)
    product = ReplayFactory(
        settings.keys,
        settings.chords,
        (Edge(1, True), Edge(1, False), Edge(3, True), Edge(3, False)),
    ).make()
    assert example["dispatch"](product, settings, live=False) == 1
    output.set_volume.assert_called_once_with(0.25)
    output.set_mute.assert_called_once_with(True)
    assert capsys.readouterr().out.splitlines() == [
        "quiet: failed (unsupported)",
        "mute: done",
    ]


def test_live_composition_selects_device_and_releases_output_without_changing_it(
    example, monkeypatch
):
    from opendeck.adapters import macos_volume, streamdock

    output = Mock(spec=macos_volume.MacOSOutputVolume)
    adapter = Mock(return_value=output)
    factory = Mock(spec=streamdock.StreamDockFactory)
    constructor = Mock(spec=streamdock.StreamDockFactory, return_value=factory)
    monkeypatch.setattr(macos_volume, "MacOSOutputVolume", adapter)
    monkeypatch.setattr(streamdock, "StreamDockFactory", constructor)
    monkeypatch.setattr(sys, "platform", "darwin")
    run = Mock(return_value=0)
    monkeypatch.setitem(example["main"].__globals__, "dispatch", run)
    assert example["main"](["--live", "--device-index", "2"]) == 0
    constructor.assert_called_once()
    assert constructor.call_args.kwargs["device_index"] == 2
    assert (
        constructor.call_args.args[2] == SCRIPT.parents[1] / "vendor" / "streamdock-sdk"
    )
    assert output.mock_calls == [("close", (), {})]
    assert run.call_args.kwargs == {"live": True}

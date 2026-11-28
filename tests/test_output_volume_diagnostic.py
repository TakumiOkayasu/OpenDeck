import runpy
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from unittest.mock import ANY, Mock, call

import pytest

from opendeck import OutputVolume, VolumeError, VolumeFailure

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "output_volume_diagnostic.py"


@pytest.fixture
def diagnostic():
    return runpy.run_path(str(SCRIPT))["main"].__globals__


@pytest.fixture
def capture(diagnostic):
    return diagnostic["capture"]


def test_records_initial_state_and_coalesced_change_on_owner(capture, monkeypatch):
    output = Mock(spec=OutputVolume)
    release = Mock()
    output.read_volume.side_effect = [0.25, 0.5]
    output.read_mute.side_effect = [False, True]

    def subscribe(observer):
        def notify():
            observer.on_change()
            observer.on_change()

        worker = Thread(target=notify)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert output.method_calls == [call.subscribe(ANY)]
        return release

    output.subscribe.side_effect = subscribe
    clock = iter((10.0, 10.0, 11.0))
    monkeypatch.setitem(capture.__globals__, "monotonic", lambda: next(clock))
    records = []

    capture(output, records.append, seconds=1)

    assert [(record["type"], record["trigger"]) for record in records] == [
        ("snapshot", "initial"),
        ("snapshot", "change"),
    ]
    assert records[0]["volume"] == {"value": 0.25}
    assert records[0]["mute"] == {"value": False}
    assert records[1]["volume"] == {"value": 0.5}
    assert records[1]["mute"] == {"value": True}
    assert output.method_calls == [
        call.subscribe(ANY),
        call.read_volume(),
        call.read_mute(),
        call.read_volume(),
        call.read_mute(),
    ]
    release.assert_called_once_with()


def test_unavailable_volume_does_not_hide_mute_state(capture):
    output = Mock(spec=OutputVolume)
    output.read_volume.side_effect = VolumeError(
        VolumeFailure.UNSUPPORTED, "no main control"
    )
    output.read_mute.return_value = False
    records = []

    capture(output, records.append, seconds=0)

    assert records == [
        {
            "type": "snapshot",
            "trigger": "initial",
            "volume": {
                "reason": "unsupported",
                "message": "unsupported: no main control",
            },
            "mute": {"value": False},
        }
    ]
    output.subscribe.return_value.assert_called_once_with()


def test_releases_subscription_when_log_write_fails(capture):
    output = Mock(spec=OutputVolume)
    write = Mock(side_effect=OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        capture(output, write, seconds=0)

    output.subscribe.return_value.assert_called_once_with()


@pytest.mark.parametrize("fails", [False, True])
def test_main_records_shutdown_only_after_releasing_output(
    diagnostic, monkeypatch, fails
):
    output = Mock(spec=OutputVolume)
    output.read_volume.return_value = 0.25
    output.read_mute.return_value = False
    steps = []

    def unsubscribe():
        steps.append("unsubscribe")
        if fails:
            raise VolumeError(VolumeFailure.FAILED, "release failed")

    @contextmanager
    def system_output():
        try:
            yield output
        finally:
            steps.append("close")

    output.subscribe.return_value = unsubscribe
    monkeypatch.setitem(diagnostic, "system_output", system_output)
    monkeypatch.setitem(diagnostic, "emit", lambda record: steps.append(record["type"]))

    if fails:
        with pytest.raises(VolumeError, match="release failed"):
            diagnostic["main"](["--seconds", "0"])
        assert steps == ["session", "snapshot", "unsubscribe", "close", "error"]
    else:
        assert diagnostic["main"](["--seconds", "0"]) == 0
        assert steps == ["session", "snapshot", "unsubscribe", "close", "finished"]


@pytest.mark.parametrize("seconds", ["-1", "nan", "inf", "1e100"])
def test_invalid_capture_time_never_opens_adapter(diagnostic, monkeypatch, seconds):
    open_output = Mock()
    monkeypatch.setitem(diagnostic, "system_output", open_output)
    with pytest.raises(SystemExit) as error:
        diagnostic["main"](["--seconds", seconds])
    assert error.value.code == 2
    open_output.assert_not_called()

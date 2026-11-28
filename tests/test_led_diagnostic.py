import json
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

import pytest

spec = spec_from_file_location(
    "n4pro_led_diagnostic",
    Path(__file__).resolve().parents[1] / "tools" / "n4pro_led_diagnostic.py",
)
assert spec is not None and spec.loader is not None
diagnostic = module_from_spec(spec)
spec.loader.exec_module(diagnostic)
COLORS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (32, 64, 128))


class Device:
    def __init__(self, result=0):
        self.calls = []
        self.result = result

    def open(self):
        self.calls.append("open")
        return True

    def set_device(self):
        self.calls.append("configure")

    def set_single_led_color(self, colors):
        self.calls.append(("colors", colors))
        return self.result

    def close(self, notify):
        self.calls.append(("close", notify))


def test_explicit_colors_send_once_and_record_result_before_close():
    device = Device()
    output = StringIO()
    assert diagnostic.run_diagnostic(device, COLORS, output) == "sdk_success"
    assert device.calls == ["open", "configure", ("colors", COLORS), ("close", False)]
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [row["type"] for row in rows] == [
        "led_request",
        "device",
        "led_result",
        "closed",
    ]
    assert rows[0]["colors"] == [list(color) for color in COLORS]
    assert rows[1]["device_class"] == "Device"
    assert rows[2]["sdk_result"] == 0
    assert rows[2]["outcome"] == "sdk_success"
    assert rows[2]["elapsed_ms"] >= 0


@pytest.mark.parametrize(
    "colors",
    [COLORS[:3], (*COLORS, (0, 0, 0)), ((256, 0, 0),) * 4, ((True, 0, 0),) * 4],
)
def test_invalid_colors_do_not_open_device(colors):
    device = Device()
    with pytest.raises(ValueError):
        diagnostic.run_diagnostic(device, colors, StringIO())
    assert device.calls == []


@pytest.mark.parametrize(
    ("result", "outcome"), [(None, "unconfirmed"), (0x04000201, "sdk_failed")]
)
def test_missing_or_failed_sdk_result_is_not_success(result, outcome):
    output = StringIO()
    assert diagnostic.run_diagnostic(Device(result), COLORS, output) == outcome
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[2]["sdk_result"] == result
    assert rows[2]["outcome"] == outcome


def test_send_failure_records_duration_and_closes():
    class FailedDevice(Device):
        def set_single_led_color(self, colors):
            raise OSError("send failed")

    device = FailedDevice()
    output = StringIO()
    with pytest.raises(OSError, match="send failed"):
        diagnostic.run_diagnostic(device, COLORS, output)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[2]["type"] == "led_failed"
    assert rows[2]["elapsed_ms"] >= 0
    assert rows[2]["error"] == "send failed"
    assert device.calls[-1] == ("close", False)


def test_send_and_cleanup_failure_preserve_both_exceptions():
    class FailedDevice(Device):
        def set_single_led_color(self, colors):
            raise OSError("send failed")

        def close(self, notify):
            raise RuntimeError("close failed")

    with pytest.raises(ExceptionGroup) as caught:
        diagnostic.run_diagnostic(FailedDevice(), COLORS, StringIO())
    assert [str(error) for error in caught.value.exceptions] == [
        "send failed",
        "close failed",
    ]


@pytest.mark.parametrize(
    "arguments",
    [[], ["FF0000"] * 3, ["FF0000"] * 5, ["GG0000", "000000", "000000", "000000"]],
)
def test_cli_requires_four_valid_colors_before_loading_sdk(arguments, monkeypatch):
    monkeypatch.setattr(
        diagnostic,
        "select_device",
        lambda *_: pytest.fail("SDK must not load"),
        raising=False,
    )
    with pytest.raises(SystemExit) as caught:
        diagnostic.main(["--colors", *arguments])
    assert caught.value.code == 2


def test_cli_records_session_index_and_returns_unconfirmed(monkeypatch, tmp_path):
    device = Device(None)
    selected = []
    monkeypatch.setattr(diagnostic, "sdk_revision", lambda _: "f" * 40)
    monkeypatch.setattr(
        diagnostic,
        "select_device",
        lambda sdk, index: selected.append((sdk, index)) or device,
        raising=False,
    )
    output = tmp_path / "led.jsonl"
    code = diagnostic.main(
        [
            "--colors",
            "FF0000",
            "00FF00",
            "0000FF",
            "204080",
            "--sdk",
            "sdk-checkout",
            "--device-index",
            "2",
            "--output",
            str(output),
        ]
    )
    assert code == 1
    assert selected == [(Path("sdk-checkout"), 2)]
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert rows[0]["type"] == "session"
    assert rows[0]["device_index"] == 2
    assert rows[0]["sdk_revision"] == "f" * 40
    assert rows[2]["device_class"] == "Device"
    assert rows[-2]["outcome"] == "unconfirmed"


def test_cli_preserves_existing_output_before_loading_sdk(monkeypatch, tmp_path):
    output = tmp_path / "existing.jsonl"
    output.write_text("existing result\n")
    monkeypatch.setattr(
        diagnostic, "select_device", lambda *_: pytest.fail("SDK must not load")
    )
    with pytest.raises(FileExistsError):
        diagnostic.main(
            [
                "--colors",
                "000000",
                "000000",
                "000000",
                "000000",
                "--output",
                str(output),
            ]
        )
    assert output.read_text() == "existing result\n"


def test_failed_open_still_attempts_cleanup_without_sending():
    class FailedDevice(Device):
        def open(self):
            self.calls.append("open")
            return False

    device = FailedDevice()
    with pytest.raises(RuntimeError, match="could not open"):
        diagnostic.run_diagnostic(device, COLORS, StringIO())
    assert device.calls == ["open", ("close", False)]


def test_sdk_close_with_running_reader_is_not_confirmed_closed():
    from types import SimpleNamespace

    device = Device()
    device.read_thread = SimpleNamespace(is_alive=lambda: True)
    output = StringIO()
    with pytest.raises(RuntimeError, match="native release is unconfirmed"):
        diagnostic.run_diagnostic(device, COLORS, output)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[-1]["type"] == "close_failed"


def test_device_metadata_records_only_available_sdk_attributes():
    device = Device()
    device.vendor_id = 0x5548
    device.product_id = 0x1021
    device.firmware_version = "1.2.3"
    assert diagnostic.device_metadata(device) == {
        "device_class": "Device",
        "vendor_id": 0x5548,
        "product_id": 0x1021,
        "firmware": "1.2.3",
    }


def test_missing_or_invalid_metadata_is_null_without_querying_device():
    device = Device()
    device.vendor_id = True
    device.firmware_version = ""
    assert diagnostic.device_metadata(device) == {
        "device_class": "Device",
        "vendor_id": None,
        "product_id": None,
        "firmware": None,
    }
    assert device.calls == []


def test_sdk_revision_uses_sdk_root_and_bounded_git_commands(monkeypatch, tmp_path):
    calls = []
    answers = iter((str(tmp_path), "f" * 40))

    def check_output(arguments, **options):
        calls.append((arguments, options))
        return next(answers) + "\n"

    monkeypatch.setattr(diagnostic.subprocess, "check_output", check_output)
    assert diagnostic.sdk_revision(tmp_path) == "f" * 40
    assert [call[0][-1] for call in calls] == ["--show-toplevel", "HEAD"]
    assert all(call[0][:3] == ["git", "-C", str(tmp_path)] for call in calls)
    assert all(call[1]["timeout"] == 2 for call in calls)


def test_sdk_revision_does_not_report_parent_repository(monkeypatch, tmp_path):
    monkeypatch.setattr(
        diagnostic.subprocess, "check_output", lambda *_, **__: str(tmp_path.parent)
    )
    assert diagnostic.sdk_revision(tmp_path) is None


def test_sdk_revision_is_null_when_git_is_unavailable(monkeypatch, tmp_path):
    def unavailable(*_, **__):
        raise FileNotFoundError("git")

    monkeypatch.setattr(diagnostic.subprocess, "check_output", unavailable)
    assert diagnostic.sdk_revision(tmp_path) is None

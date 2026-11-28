"""Send one explicit set of N4 Pro LED colors and record the SDK result."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, TextIO


def sdk_revision(path: Path) -> str | None:
    command = ["git", "-C", str(path), "rev-parse"]
    try:
        root = subprocess.check_output(
            [*command, "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
        if Path(root).resolve() != path.resolve():
            return None
        return (
            subprocess.check_output(
                [*command, "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).strip()
            or None
        )
    except OSError, subprocess.SubprocessError:  # codex-rule-ignore: metadata optional
        return None


def device_metadata(device: object) -> dict[str, object]:
    metadata: dict[str, object] = {"device_class": type(device).__name__}
    for field in ("vendor_id", "product_id"):
        value = getattr(device, field, None)
        metadata[field] = value if type(value) is int and 0 <= value <= 0xFFFF else None
    firmware = getattr(device, "firmware_version", None)
    metadata["firmware"] = firmware if isinstance(firmware, str) and firmware else None
    return metadata


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--colors", required=True, nargs=4, type=parse_color)
    parser.add_argument("--sdk", type=Path, default=Path("vendor/streamdock-sdk"))
    parser.add_argument("--device-index", type=device_index)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output_path = args.output or Path("logs") / time.strftime("led-%Y%m%d-%H%M%S.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        write_record(
            output,
            "session",
            schema_version=1,
            sdk_path=str(args.sdk),
            sdk_revision=sdk_revision(args.sdk),
            device_index=args.device_index,
            system=platform.platform(),
        )
        try:
            device = select_device(args.sdk, args.device_index)
            outcome = run_diagnostic(device, args.colors, output)
        except (
            BaseException
        ) as error:  # codex-rule-ignore: record then propagate failure
            record_failure(output, "error", error)
            raise
    return 0 if outcome == "sdk_success" else 1


def parse_color(value: str) -> tuple[int, int, int]:
    if len(value) != 6 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise argparse.ArgumentTypeError(
            "Colors must have six hexadecimal digits RRGGBB"
        )
    return (int(value[:2], 16), int(value[2:4], 16), int(value[4:], 16))


def device_index(value: str) -> int:
    index = int(value)
    if index < 0:
        raise argparse.ArgumentTypeError("Device index must be nonnegative")
    return index


def select_device(sdk: Path, index: int | None) -> Device:
    from opendeck.adapters.streamdock import StreamDockFactory

    device, _ = StreamDockFactory({}, (), sdk, index)._select()
    return device


class Device(Protocol):
    def open(self) -> bool: ...

    def set_device(self) -> None: ...

    def set_single_led_color(self, colors: Sequence[Sequence[int]]) -> int | None: ...

    def close(self, *, notify: bool) -> None: ...


def validate_colors(colors: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    if len(colors) != 4 or any(
        len(color) != 3
        or any(type(value) is not int or not 0 <= value <= 255 for value in color)
        for color in colors
    ):
        raise ValueError(
            "Exactly four RGB colors with integer channels 0..255 required"
        )
    return tuple(tuple(color) for color in colors)


def write_record(output: TextIO, kind: str, **fields: object) -> None:
    record = {
        "type": kind,
        "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "monotonic_ns": time.monotonic_ns(),
        **fields,
    }
    output.write(json.dumps(record, ensure_ascii=False) + "\n")
    output.flush()


def run_diagnostic(
    device: Device, colors: Sequence[Sequence[int]], output: TextIO
) -> str:
    colors = validate_colors(colors)
    write_record(output, "led_request", colors=colors)
    failure: BaseException | None = None
    try:
        if not device.open():
            raise RuntimeError("SDK could not open the selected N4 Pro")
        device.set_device()
        write_record(output, "device", **device_metadata(device))
        return send_colors(device, colors, output)
    except BaseException as error:  # codex-rule-ignore: preserve primary during cleanup
        failure = error
        raise
    finally:
        close_device(device, output, failure)


def send_colors(device: Device, colors: Sequence[Sequence[int]], output: TextIO) -> str:
    started = time.perf_counter_ns()
    try:
        result = device.set_single_led_color(colors)
    except Exception as error:  # codex-rule-ignore: record and propagate send error
        record_failure(
            output,
            "led_failed",
            error,
            elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
        )
        raise
    outcome = "unconfirmed" if result is None else "sdk_failed"
    if result == 0:
        outcome = "sdk_success"
    write_record(
        output,
        "led_result",
        sdk_result=result,
        outcome=outcome,
        elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
    )
    return outcome


def record_failure(
    output: TextIO, kind: str, error: BaseException, **fields: object
) -> None:
    try:
        write_record(
            output, kind, error=str(error), error_type=type(error).__name__, **fields
        )
    except OSError as log_error:  # codex-rule-ignore: retain original failure
        error.add_note(f"Diagnostic log write also failed: {log_error}")


def close_device(device: Device, output: TextIO, failure: BaseException | None) -> None:
    try:
        device.close(notify=False)
        workers = (
            getattr(device, "read_thread", None),
            getattr(device, "heartbeat_thread", None),
        )
        if any(worker is not None and worker.is_alive() for worker in workers):
            raise RuntimeError("SDK worker did not stop; native release is unconfirmed")
    except BaseException as error:  # codex-rule-ignore: preserve cleanup failure
        record_failure(output, "close_failed", error)
        if failure is not None:
            raise BaseExceptionGroup(
                "LED diagnostic and cleanup failed", [failure, error]
            ) from None
        raise
    if failure is None:
        write_record(output, "closed")
    else:
        try:
            write_record(output, "closed")
        except OSError as log_error:  # codex-rule-ignore: retain primary failure
            failure.add_note(f"Diagnostic close record failed: {log_error}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Record read-only observations of the current default output."""

import argparse
import json
import platform
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from threading import TIMEOUT_MAX, Event
from time import monotonic

from opendeck import Observer, OutputVolume, VolumeError
from opendeck.adapters._system_volume import system_output


class Updates(Observer):
    def __init__(self) -> None:
        self._pending = Event()

    def on_change(self) -> None:
        self._pending.set()

    def wait(self, seconds: float) -> bool:
        if not self._pending.wait(seconds):
            return False
        self._pending.clear()
        return True


def failure(error: VolumeError) -> dict[str, str]:
    return {"reason": error.reason.value, "message": str(error)}


def read(operation: Callable[[], float | bool]) -> dict[str, object]:
    try:
        return {"value": operation()}
    except VolumeError as error:  # codex-rule-ignore: serialize expected read failures
        return failure(error)


def snapshot(output: OutputVolume, trigger: str) -> dict[str, object]:
    return {
        "type": "snapshot",
        "trigger": trigger,
        "volume": read(output.read_volume),
        "mute": read(output.read_mute),
    }


def capture(
    output: OutputVolume,
    write: Callable[[dict[str, object]], None],
    *,
    seconds: float,
) -> None:
    updates = Updates()
    unsubscribe = output.subscribe(updates)
    try:
        deadline = monotonic() + seconds
        write(snapshot(output, "initial"))
        while (remaining := deadline - monotonic()) > 0 and updates.wait(remaining):
            write(snapshot(output, "change"))
    finally:
        unsubscribe()


def emit(record: dict[str, object]) -> None:
    line = json.dumps({"time": datetime.now(UTC).isoformat(), **record})
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seconds",
        type=float,
        default=30,
        help="seconds to observe changes (0 for one initial snapshot)",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.seconds <= TIMEOUT_MAX:
        parser.error(f"--seconds must be between 0 and {TIMEOUT_MAX}")
    emit({"type": "session", "platform": platform.platform(), "seconds": args.seconds})
    try:
        with system_output() as output:
            capture(output, emit, seconds=args.seconds)
    except KeyboardInterrupt:  # codex-rule-ignore: report normal cancellation
        emit({"type": "stopped"})
        return 130
    except VolumeError as error:  # codex-rule-ignore: emit failure and propagate it
        emit({"type": "error", **failure(error)})
        raise
    emit({"type": "finished"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

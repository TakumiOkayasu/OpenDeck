import argparse
import json
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from opendeck import (
    Action,
    Observer,
    OutputVolume,
    Result,
    Slot,
    Status,
    VolumeError,
)
from opendeck.adapters._system_volume import system_output
from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.config import Settings, parse
from opendeck.ports import Product
from opendeck.runtime import Wake, drain


@dataclass(frozen=True, slots=True)
class SetVolume(Action):
    output: OutputVolume
    level: float

    def run(self) -> Result:
        try:
            self.output.set_volume(self.level)
        except (
            VolumeError
        ) as error:  # codex-rule-ignore: report expected output failure
            return Result(Status.FAILED, str(error))
        return Result(Status.DONE)


@dataclass(frozen=True, slots=True)
class SetMute(Action):
    output: OutputVolume
    muted: bool

    def run(self) -> Result:
        try:
            self.output.set_mute(self.muted)
        except (
            VolumeError
        ) as error:  # codex-rule-ignore: report expected output failure
            return Result(Status.FAILED, str(error))
        return Result(Status.DONE)


def configure(value: object, output: OutputVolume) -> Settings:
    def build_volume(options: Mapping[str, object]) -> Action:
        level = options.get("level")
        if (
            set(options) != {"level"}
            or isinstance(level, bool)
            or not isinstance(level, (float, int))
            or not 0.0 <= level <= 1.0
        ):
            raise ValueError("volume expects only a level between 0 and 1")
        return SetVolume(output, level)

    def build_mute(options: Mapping[str, object]) -> Action:
        muted = options.get("muted")
        if set(options) != {"muted"} or not isinstance(muted, bool):
            raise ValueError("mute expects only a muted boolean")
        return SetMute(output, muted)

    return parse(value, {"volume": build_volume, "mute": build_mute})


class DemoOutput(OutputVolume):
    def __init__(self) -> None:
        self._level = 0.5
        self._muted = False
        self._observers: list[Observer] = []

    def read_volume(self) -> float:
        return self._level

    def set_volume(self, level: float) -> None:
        self._level = level
        print(f"volume={level:.2f}")  # codex-rule-ignore: sample console output
        self._notify()

    def read_mute(self) -> bool:
        return self._muted

    def set_mute(self, muted: bool) -> None:
        self._muted = muted
        print(f"muted={muted}")  # codex-rule-ignore: sample console output
        self._notify()

    def subscribe(self, observer: Observer) -> Callable[[], None]:
        self._observers.append(observer)

        def unsubscribe() -> None:
            if observer in self._observers:
                self._observers.remove(observer)

        return unsubscribe

    def _notify(self) -> None:
        for observer in tuple(self._observers):
            observer.on_change()


def dispatch(product: Product, settings: Settings, *, live: bool) -> int:
    failed = False

    def report(slot: Slot, result: Result | None) -> None:
        nonlocal failed
        if result is None:
            print(f"{slot}: unassigned")  # codex-rule-ignore: sample console output
            return
        failed |= result.status != Status.DONE
        detail = f" ({result.detail})" if result.detail else ""
        print(  # codex-rule-ignore: sample console output
            f"{slot}: {result.status.value}{detail}"
        )

    wake = Wake()
    with ExitStack() as owned:
        owned.callback(product.link.close)
        product.subject.add(wake)
        owned.callback(product.subject.remove, wake)
        product.link.open()
        if live:
            print(  # codex-rule-ignore: live sample readiness feedback
                "INPUT OK. Configured buttons are ready. Ctrl+C ends.",
                flush=True,
            )
        try:
            while True:
                drain(product.input, settings.binding, report)
                if not live:
                    break
                wake.wait()
        except KeyboardInterrupt:  # codex-rule-ignore: normal foreground cancellation
            print("Stopped.")  # codex-rule-ignore: sample console output
    return int(failed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="N4 Pro default-output volume example")
    parser.add_argument(
        "--live",
        action="store_true",
        help="control the actual default output from an N4 Pro",
    )
    parser.add_argument("--device-index", type=int)
    args = parser.parse_args(argv)
    with ExitStack() as owned:
        output: OutputVolume = DemoOutput()
        if args.live:
            output = owned.enter_context(system_output())
        value = json.loads(
            Path(__file__).with_name("output-volume.json").read_text(encoding="utf-8")
        )
        settings = configure(value, output)
        if args.live:
            from opendeck.adapters.streamdock import StreamDockFactory

            sdk = Path(__file__).resolve().parents[1] / "vendor" / "streamdock-sdk"
            product = StreamDockFactory(
                settings.keys, settings.chords, sdk, device_index=args.device_index
            ).make()
        else:
            print(  # codex-rule-ignore: sample mode feedback
                "SIMULATION: output changes are recorded locally."
            )
            events = tuple(
                edge
                for key in range(1, 5)
                for edge in (Edge(key, True), Edge(key, False))
            )
            product = ReplayFactory(settings.keys, settings.chords, events).make()
        return dispatch(product, settings, live=args.live)


if __name__ == "__main__":
    raise SystemExit(main())

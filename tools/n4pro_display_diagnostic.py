"""Manual N4 Pro display and input diagnostic. No actions are bound."""

from __future__ import annotations

import argparse
import json
import logging
import math
import platform
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from opendeck import Slot, View
    from opendeck.ports import SurfaceProduct


_WRITE_LOCK = threading.Lock()


class CallbackLog(logging.Handler):
    def __init__(self, output: TextIO) -> None:
        super().__init__()
        self.output = output
        self.sequence = 0
        self.error: OSError | None = None
        self.accepting = True

    def emit(self, record: logging.LogRecord) -> None:
        fields = getattr(record, "diagnostic", None)
        if not self.accepting or fields is None or self.error is not None:
            return
        self.sequence += 1
        fields = dict(fields)
        kind = fields.pop("kind")
        try:
            write_record(
                self.output, kind, observation_sequence=self.sequence, **fields
            )
        except OSError as error:  # codex-rule-ignore: retain I/O error for owner
            # The SDK catches callback exceptions. Surface I/O failure on the owner.
            error.add_note("SDK diagnostic logging failed while the input callback ran")
            self.error = error

    def close(self) -> None:
        self.acquire()
        try:
            self.accepting = False
            super().close()
        finally:
            self.release()


@contextmanager
def observe_sdk(output: TextIO) -> Iterator[None]:
    logger = logging.getLogger("opendeck.adapters.streamdock")
    handler = CallbackLog(output)
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
        handler.close()
    if handler.error is not None:
        raise handler.error


def targets() -> dict[str, int]:
    return {f"display-{number}": number for number in range(1, 15)}


def make_image(label: str, size: tuple[int, int]) -> bytes:
    image = Image.new("RGBA", size, (18, 35, 52, 255))
    draw = ImageDraw.Draw(image)
    width, height = size

    for x in range(0, width, max(width // 8, 1)):
        draw.line((x, 0, x, height), fill=(70, 100, 120, 255))

    for y in range(0, height, max(height // 4, 1)):
        draw.line((0, y, width, y), fill=(70, 100, 120, 255))

    draw.rectangle((0, 0, width - 1, height - 1), outline="white", width=3)
    draw.rectangle((5, 5, 16, 16), fill="red")
    draw.rectangle((width - 17, 5, width - 6, 16), fill="lime")

    draw.text((width // 2 - 20, height // 2 - 5), label, fill="white")

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def write_record(output: TextIO, kind: str, **fields: object) -> None:
    with _WRITE_LOCK:
        record = {
            "type": kind,
            "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "monotonic_ns": time.monotonic_ns(),
            **fields,
        }
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
        output.flush()


def revision(path: Path) -> str | None:
    try:
        root = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if Path(root).resolve() != path.resolve():
            return None
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except OSError, subprocess.CalledProcessError:
        return None


def draw_image(
    view: View, output: TextIO, target: str, label: str, size: tuple[int, int]
) -> None:
    image = make_image(label, size)
    started = time.perf_counter_ns()
    try:
        view.draw(image)
    except Exception:
        write_record(
            output,
            "image_failed",
            target=target,
            label=label,
            elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
        )
        raise
    write_record(
        output,
        "image_sent",
        target=target,
        label=label,
        elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
    )


def draw_images(
    product: SurfaceProduct, images: dict[Slot, int], output: TextIO
) -> None:
    draw_image(product.screen, output, "background", "BG", (800, 480))
    print("背景画像を送信しました。実機に表示されたか確認してください。", flush=True)
    input("Enterキーを押すとボタンと副画面の画像を送信します: ")
    draw_targets(product, images, output)


def draw_targets(
    product: SurfaceProduct, images: dict[Slot, int], output: TextIO
) -> None:
    for slot, number in images.items():
        size = (112, 112) if number <= 10 else (176, 112)
        draw_image(product.images[slot], output, str(slot), f"D{number}", size)
        sys.stdout.write(f"表示先 {number} に画像 D{number} を送信しました\n")
        sys.stdout.flush()


def probe_image_order(
    product: SurfaceProduct, images: dict[Slot, int], output: TextIO, order: str
) -> None:
    for phase, operation in enumerate(order.split("-"), start=1):
        label = "背景" if operation == "background" else "ボタンと副画面の画像"
        input(
            f"工程{phase}: 現在の表示を確認し、Enterキーを押すと{label}を送信します: "
        )
        write_record(output, "image_phase_start", phase=phase, operation=operation)
        if operation == "background":
            draw_image(product.screen, output, "background", f"BG{phase}", (800, 480))
        else:
            draw_targets(product, images, output)
        write_record(output, "image_phase_end", phase=phase, operation=operation)
    input("最後の画像を目視・撮影し、Enterキーを押すと終了します: ")


def drain_inputs(product: SurfaceProduct, output: TextIO, step: str | None) -> None:
    from opendeck import TouchPoint

    while (slot := product.input.take()) is not None:
        write_record(output, "button", step=step, slot=str(slot))
    while (event := product.touch.take()) is not None:
        if isinstance(event, TouchPoint):
            write_record(output, "touch", step=step, x=event.x, y=event.y)
        else:
            write_record(output, "swipe", step=step, direction=str(event.direction))


def capture_step(
    product: SurfaceProduct, output: TextIO, step: str, seconds: float
) -> None:
    drain_inputs(product, output, None)
    write_record(output, "step_start", step=step)
    sys.stdout.write(f"開始: 案内された操作を行ってください ({seconds:g}秒間)\n")
    sys.stdout.flush()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        drain_inputs(product, output, step)
        time.sleep(0.05)
    write_record(output, "step_end", step=step)
    print("この操作の記録を終了しました。", flush=True)


def input_steps() -> dict[str, str]:
    return dict(
        [
            ("touch_top_left", "タッチパネルの左上に触れる"),
            ("touch_top_right", "タッチパネルの右上に触れる"),
            ("touch_center", "タッチパネルの中央に触れる"),
            ("touch_bottom_left", "タッチパネルの左下に触れる"),
            ("touch_bottom_right", "タッチパネルの右下に触れる"),
            ("swipe_left", "タッチパネルを右から左へなぞる ←"),
            ("swipe_right", "タッチパネルを左から右へなぞる →"),
            *[
                (f"button_{n}", f"ボタン{n}を押す (左上から右へ数える)")
                for n in range(1, 11)
            ],
        ]
    )


def optional_input_steps() -> dict[str, str]:
    steps = {
        "touch_hold": "タッチパネルの中央に1本の指で触れ、記録終了まで保持する",
        "touch_drag": "タッチパネルの左上から右下まで、指を離さずゆっくりなぞる",
        "touch_two_fingers": "タッチパネルの中央付近に2本の指で同時に触れ、離す",
    }
    for number in range(1, 5):
        steps[f"secondary_{number}"] = (
            f"副画面の左から{number}番目の領域の中央に触れ、指を離す"
        )
        position = f"正面から見て左から{number}番目のノブ"
        steps[f"knob_{number}_press_release"] = f"{position}を押して離す"
        for direction, movement in (
            ("left", "左へ1目盛り回す (反時計回り)"),
            ("right", "右へ1目盛り回す (時計回り)"),
        ):
            steps[f"knob_{number}_{direction}"] = f"{position}を押さずに{movement}"
            steps[f"knob_{number}_held_{direction}"] = (
                f"{position}を押したまま準備し、開始後に{movement}。記録終了まで押し続ける"
            )
    return steps


def record_inputs(
    product: SurfaceProduct,
    output: TextIO,
    selected: tuple[str, ...] = (),
    seconds: float = 5,
) -> None:
    steps = input_steps()
    instructions = steps | optional_input_steps()
    for step in selected or steps:
        instruction = instructions[step]
        input(
            f"次の操作: {instruction}\n"
            "Enterキーを押し、開始の表示後に操作してください: "
        )
        capture_step(product, output, step, seconds)


def run(
    product: SurfaceProduct,
    images: dict[Slot, int],
    output: TextIO,
    steps: tuple[str, ...] = (),
    seconds: float = 5,
    image_order: str | None = None,
) -> None:
    try:
        product.link.open()
        try:
            if image_order is not None:
                probe_image_order(product, images, output, image_order)
            else:
                if not steps:
                    input("Enterキーを押すと背景画像 BG を送信します: ")
                    draw_images(product, images, output)
                    input("画像を確認し、Enterキーを押すと入力の記録を始めます: ")
                record_inputs(product, output, steps, seconds)
        finally:
            product.link.close()
    except KeyboardInterrupt:
        write_record(output, "stopped")
        print("\n中断しました。", flush=True)
    except Exception as error:
        record_error(output, error)
        raise
    else:
        write_record(output, "finished")
        print("診断が正常に終了しました。記録先のJSONLを確認してください。", flush=True)


def record_error(output: TextIO, error: Exception) -> None:
    write_record(
        output,
        "error",
        error_type=type(error).__name__,
        message=str(error),
        traceback=traceback.format_exc(),
    )


def parse_args() -> argparse.Namespace:
    filename = datetime.now().strftime("n4pro-diagnostic-%Y%m%d-%H%M%S-%f.jsonl")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=Path("vendor/streamdock-sdk"))
    parser.add_argument("--device-index", type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--step",
        action="append",
        choices=input_steps() | optional_input_steps(),
        default=[],
        help="capture this input step without drawing images; repeat to select more",
    )
    mode.add_argument(
        "--image-order",
        choices=("background-images-background", "images-background"),
        help="observe only this sequence of background and individual image updates",
    )
    parser.add_argument(
        "--seconds", type=float, default=5, help="seconds per input step"
    )
    parser.add_argument(
        "--output", type=Path, default=Path(f"logs/diagnostics/{filename}")
    )
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be finite and greater than zero")
    return args


def main() -> None:
    from opendeck import Slot
    from opendeck.adapters.streamdock import StreamDockFactory

    args = parse_args()
    path = args.output

    # Separate identities ensure image targets never stand in for input events.
    inputs = {n: Slot(f"input-{n}") for n in range(1, 16)}
    images = {Slot(name): n for name, n in targets().items()}

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output, observe_sdk(output):
        print(f"記録先: {path}", flush=True)
        write_record(
            output,
            "session",
            schema_version=2,
            platform=platform.platform(),
            python=platform.python_version(),
            revision=revision(Path.cwd()),
            sdk_revision=revision(args.sdk),
            device_index=args.device_index,
            steps=args.step,
            capture_seconds=args.seconds,
            image_order=args.image_order,
        )
        try:
            factory = StreamDockFactory(inputs, (), args.sdk, args.device_index)
            product = factory.make_surface(images)
        except Exception as error:
            record_error(output, error)
            raise
        run(product, images, output, tuple(args.step), args.seconds, args.image_order)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"診断に失敗しました: {error}", file=sys.stderr, flush=True)
        raise

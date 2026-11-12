"""Manual N4 Pro display and input diagnostic. No actions are bound."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from opendeck import Slot
    from opendeck.ports import SurfaceProduct


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
    record = {
        "type": kind,
        "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
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


def draw_images(
    product: SurfaceProduct, images: dict[Slot, int], output: TextIO
) -> None:
    product.screen.draw(make_image("BG", (800, 480)))
    write_record(output, "image_sent", target="background")
    print("背景画像を送信しました。実機に表示されたか確認してください。", flush=True)
    input("Enterキーを押すとボタンと副画面の画像を送信します: ")
    for slot, number in images.items():
        size = (112, 112) if number <= 10 else (176, 112)
        product.images[slot].draw(make_image(f"D{number}", size))
        write_record(output, "image_sent", target=str(slot), label=f"D{number}")
        print(f"表示先 {number} に画像 D{number} を送信しました", flush=True)


def drain_inputs(product: SurfaceProduct, output: TextIO, step: str | None) -> None:
    while (slot := product.input.take()) is not None:
        write_record(output, "button", step=step, slot=str(slot))
    while (event := product.touch.take()) is not None:
        if hasattr(event, "x"):
            write_record(output, "touch", step=step, x=event.x, y=event.y)
        else:
            write_record(output, "swipe", step=step, direction=str(event.direction))


def capture_step(
    product: SurfaceProduct, output: TextIO, step: str, seconds: float
) -> None:
    drain_inputs(product, output, None)
    write_record(output, "step_start", step=step)
    print("開始: 案内された操作を行ってください (5秒間)", flush=True)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        drain_inputs(product, output, step)
        time.sleep(0.05)
    write_record(output, "step_end", step=step)
    print("この操作の記録を終了しました。", flush=True)


def record_inputs(product: SurfaceProduct, output: TextIO) -> None:
    steps = [
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
    for step, instruction in steps:
        input(
            f"次の操作: {instruction}\n"
            "Enterキーを押し、開始の表示後に操作してください: "
        )
        capture_step(product, output, step, 5)


def run(product: SurfaceProduct, images: dict[Slot, int], output: TextIO) -> None:
    try:
        product.link.open()
        try:
            input("Enterキーを押すと背景画像 BG を送信します: ")
            draw_images(product, images, output)
            input("画像を確認し、Enterキーを押すと入力の記録を始めます: ")
            record_inputs(product, output)
        finally:
            product.link.close()
    except KeyboardInterrupt:
        write_record(output, "stopped")
        print("\n中断しました。", flush=True)
    except Exception as error:
        write_record(
            output,
            "error",
            error_type=type(error).__name__,
            message=str(error),
            traceback=traceback.format_exc(),
        )
        raise
    else:
        write_record(output, "finished")
        print("診断が正常に終了しました。記録先のJSONLを確認してください。", flush=True)


def main() -> None:
    from opendeck import Slot
    from opendeck.adapters.streamdock import StreamDockFactory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=Path("vendor/streamdock-sdk"))
    parser.add_argument("--device-index", type=int)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    filename = datetime.now().strftime("n4pro-diagnostic-%Y%m%d-%H%M%S-%f.jsonl")
    path = args.output or Path(filename)

    # Separate identities ensure image targets never stand in for input events.
    inputs = {n: Slot(f"input-{n}") for n in range(1, 16)}
    images = {Slot(name): n for name, n in targets().items()}
    with path.open("x", encoding="utf-8") as output:
        print(f"記録先: {path}", flush=True)
        write_record(
            output,
            "session",
            schema_version=1,
            platform=platform.platform(),
            python=platform.python_version(),
            revision=revision(Path.cwd()),
            sdk_revision=revision(args.sdk),
            device_index=args.device_index,
        )
        try:
            factory = StreamDockFactory(inputs, (), args.sdk, args.device_index)
            product = factory.make_surface(images)
        except Exception as error:
            write_record(
                output,
                "error",
                error_type=type(error).__name__,
                message=str(error),
                traceback=traceback.format_exc(),
            )
            raise
        run(product, images, output)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"診断に失敗しました: {error}", file=sys.stderr, flush=True)
        raise

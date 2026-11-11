"""Manual N4 Pro display and input diagnostic. No actions are bound."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
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
    print("Background sent; physical completion is unconfirmed.", flush=True)
    input("Press Enter to send button and panel images: ")
    for slot, number in images.items():
        size = (112, 112) if number <= 10 else (176, 112)
        product.images[slot].draw(make_image(f"D{number}", size))
        write_record(output, "image_sent", target=str(slot), label=f"D{number}")
        print(f"Sent image D{number} to display target {number}", flush=True)


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
    print(f"GO: {step}", flush=True)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        drain_inputs(product, output, step)
        time.sleep(0.05)
    write_record(output, "step_end", step=step)


def record_inputs(product: SurfaceProduct, output: TextIO) -> None:
    steps = [
        ("touch_top_left", "Touch top left"),
        ("touch_top_right", "Touch top right"),
        ("touch_center", "Touch center"),
        ("touch_bottom_left", "Touch bottom left"),
        ("touch_bottom_right", "Touch bottom right"),
        ("swipe_left", "Swipe left"),
        ("swipe_right", "Swipe right"),
        *[(f"button_{n}", f"Press button {n} in reading order") for n in range(1, 11)],
    ]
    for step, instruction in steps:
        input(f"Press Enter, then {instruction} after GO (5 seconds): ")
        capture_step(product, output, step, 5)


def run(product: SurfaceProduct, images: dict[Slot, int], output: TextIO) -> None:
    try:
        product.link.open()
        try:
            input("Press Enter to send background BG (observe before continuing): ")
            draw_images(product, images, output)
            input("Observe the images; press Enter to record inputs: ")
            record_inputs(product, output)
        finally:
            product.link.close()
    except KeyboardInterrupt:
        write_record(output, "stopped")
        print("\nStopped.", flush=True)
    except Exception as error:
        write_record(
            output, "error", error_type=type(error).__name__, message=str(error)
        )
        raise
    else:
        write_record(output, "finished")


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
        print(f"Recording to {path}", flush=True)
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
                output, "error", error_type=type(error).__name__, message=str(error)
            )
            raise
        run(product, images, output)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Diagnostic failed: {error}", file=sys.stderr, flush=True)
        raise

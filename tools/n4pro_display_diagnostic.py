"""Manual N4 Pro display and input diagnostic. No actions are bound."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

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


def draw_images(product: SurfaceProduct, images: dict[Slot, int]) -> None:
    product.screen.draw(make_image("BG", (800, 480)))
    print("Background sent; physical completion is unconfirmed.", flush=True)
    input("Press Enter to send button and panel images: ")
    for slot, number in images.items():
        size = (112, 112) if number <= 10 else (176, 112)
        product.images[slot].draw(make_image(f"D{number}", size))
        print(f"Sent image D{number} to display target {number}", flush=True)


def record_inputs(product: SurfaceProduct) -> None:
    print("Recording; test one operation at a time. Ctrl+C stops.", flush=True)
    while True:
        for kind, source in (("input", product.input), ("touch", product.touch)):
            while (event := source.take()) is not None:
                stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
                print(f"{stamp} {kind} {event!r}", flush=True)
        time.sleep(0.05)


def run(product: SurfaceProduct, images: dict[Slot, int]) -> None:
    product.link.open()
    try:
        input("Press Enter to send background BG (observe before continuing): ")
        draw_images(product, images)
        input("Observe the images; press Enter to record inputs, Ctrl+C to stop: ")
        record_inputs(product)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        product.link.close()


def main() -> None:
    from opendeck import Slot
    from opendeck.adapters.streamdock import StreamDockFactory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=Path("vendor/streamdock-sdk"))
    parser.add_argument("--device-index", type=int)
    args = parser.parse_args()

    # Separate identities ensure image targets never stand in for input events.
    inputs = {n: Slot(f"input-{n}") for n in range(1, 16)}
    images = {Slot(name): n for name, n in targets().items()}
    factory = StreamDockFactory(inputs, (), args.sdk, args.device_index)
    run(factory.make_surface(images), images)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Diagnostic failed: {error}", file=sys.stderr, flush=True)
        raise

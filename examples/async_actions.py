"""Replay A, A, B. B resumes the first A. The second A runs last."""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.host import AsyncHost
from opendeck.model import Result, Slot, Status
from opendeck.ports import SurfaceProduct


def button_label(slot: Slot, number: int) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (112, 112), "#172434")
    draw = ImageDraw.Draw(image)
    draw.text((56, 46), slot, anchor="mm", font_size=68, fill="white")
    draw.text((56, 93), str(number), anchor="mm", font_size=22, fill="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def mark(message: str) -> None:
    print(f"{datetime.now(UTC).isoformat()} {message}", file=sys.stderr, flush=True)


async def main(live: bool, live_seconds: float | None = None) -> None:
    a, b = Slot("A"), Slot("B")
    resume = asyncio.Event()

    class ReadState:
        async def run(self) -> Result:
            await resume.wait()
            return Result(Status.DONE)

    class Resume:
        async def run(self) -> Result:
            resume.set()
            return Result(Status.DONE)

    def report(slot: Slot, result: Result | None) -> None:
        status = result.status.value if result else "unassigned"
        detail = f" ({result.detail})" if result and result.detail else ""
        print(f"{slot} {status}{detail}")

    keys = {1: a, 2: b}
    if live:
        from opendeck.adapters.streamdock import StreamDockFactory

        sdk = Path(__file__).resolve().parents[1] / "vendor" / "streamdock-sdk"
        product = StreamDockFactory(keys, (), sdk).make_surface(
            {slot: number for number, slot in keys.items()}
        )
    else:
        events = tuple(Edge(k, down) for k in (1, 1, 2) for down in (True, False))
        product = ReplayFactory(keys, (), events).make()
    try:
        product.link.open()
        if isinstance(product, SurfaceProduct):
            for number, slot in keys.items():
                product.images[slot].draw(button_label(slot, number))
        # Timeout cancels the listener and task group just as Ctrl+C cancels main.
        deadline = asyncio.timeout(live_seconds)
        try:
            async with deadline, asyncio.TaskGroup() as tasks:
                host = AsyncHost(tasks, report, pending_limit=2)
                host.bind(ReadState(), [a])
                host.bind(Resume(), [b])
                if live:
                    if live_seconds is None:
                        print(
                            "Live: N4 Pro. Press and release A, A, B. Ctrl+C to exit.",
                            file=sys.stderr,
                            flush=True,
                        )
                    else:
                        mark("sample ready")
                    await host.listen(product.input, product.subject)
                else:
                    print("Replay: running A, A, B once.", file=sys.stderr, flush=True)
                    while (slot := product.input.take()) is not None:
                        host.dispatch(slot)
        except TimeoutError:
            if not deadline.expired():
                raise
    finally:
        if live_seconds is not None:
            mark("link close started")
        product.link.close()
        if live_seconds is not None:
            mark("link closed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="read an N4 Pro until Ctrl+C"
    )
    parser.add_argument(
        "--live-seconds", type=int, help="stop the live sample after this many seconds"
    )
    args = parser.parse_args()
    if args.live_seconds is not None and (not args.live or args.live_seconds <= 0):
        parser.error("--live-seconds requires --live and a positive duration")
    try:
        asyncio.run(main(args.live, args.live_seconds))
    except KeyboardInterrupt:
        if args.live_seconds is not None:
            raise

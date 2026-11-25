"""Check async actions with replay or N4 Pro input. See async_actions.md."""

import argparse
import asyncio
import sys
from contextlib import suppress
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.host import AsyncHost
from opendeck.model import Result, Slot, Status
from opendeck.ports import Input, SurfaceProduct


def button_label(slot: Slot, number: int) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (112, 112), "#172434")
    draw = ImageDraw.Draw(image)
    draw.text((56, 46), slot, anchor="mm", font_size=68, fill="white")
    draw.text((56, 93), str(number), anchor="mm", font_size=22, fill="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@dataclass(frozen=True)
class WaitForB:
    released: asyncio.Event

    async def run(self) -> Result:
        await self.released.wait()
        return Result(Status.DONE)


@dataclass(frozen=True)
class ResumeA:
    released: asyncio.Event

    async def run(self) -> Result:
        self.released.set()
        return Result(Status.DONE)


@dataclass(frozen=True)
class TraceInput(Input[Slot]):
    source: Input[Slot]

    def take(self) -> Slot | None:
        slot = self.source.take()
        if slot is not None:
            print(f"{slot} received", flush=True)
        return slot


def report(slot: Slot, result: Result | None) -> None:
    status = result.status.value if result is not None else "unassigned"
    detail = f" ({result.detail})" if result is not None and result.detail else ""
    print(f"{slot} {status}{detail}", flush=True)


async def main(live: bool) -> None:
    a, b = Slot("A"), Slot("B")
    released = asyncio.Event()
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
        source = TraceInput(product.input)
        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, report, pending_limit=2)
            host.bind(WaitForB(released), [a])
            host.bind(ResumeA(released), [b])
            if live:
                print(
                    "Live: N4 Pro. Press and release A or B. Ctrl+C to exit.",
                    file=sys.stderr,
                    flush=True,
                )
                await host.listen(source, product.subject)
            else:
                print("Replay: running A, A, B once.", file=sys.stderr, flush=True)
                while (slot := source.take()) is not None:
                    host.dispatch(slot)
    finally:
        product.link.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="read an N4 Pro until Ctrl+C"
    )
    with suppress(KeyboardInterrupt):
        asyncio.run(main(parser.parse_args().live))

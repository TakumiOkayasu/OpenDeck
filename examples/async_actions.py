"""Replay A, A, B. B resumes the first A. The second A runs last."""

import argparse
import asyncio
import sys
from contextlib import ExitStack, suppress
from io import BytesIO
from pathlib import Path

from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.host import AsyncHost, Resource
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


async def main(live: bool) -> None:
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
    with ExitStack() as page:
        page.callback(product.link.close)
        product.link.open()
        resources = (
            {
                slot: Resource(frozenset({slot}), view)
                for slot, view in product.images.items()
            }
            if isinstance(product, SurfaceProduct)
            else {}
        )
        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, report, resources, pending_limit=2)
            for number, action in ((1, ReadState()), (2, Resume())):
                slot = keys[number]
                displays = [slot] if slot in resources else []
                assignment = host.bind(action, [slot], displays)
                page.callback(assignment.unbind)
                if displays:
                    assignment.view(slot).draw(button_label(slot, number))
            if live:
                print(
                    "Live: N4 Pro. Press and release A, A, B. Ctrl+C to exit.",
                    file=sys.stderr,
                    flush=True,
                )
                await host.listen(product.input, product.subject)
            else:
                print("Replay: running A, A, B once.", file=sys.stderr, flush=True)
                while (slot := product.input.take()) is not None:
                    host.dispatch(slot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="read an N4 Pro until Ctrl+C"
    )
    with suppress(KeyboardInterrupt):
        asyncio.run(main(parser.parse_args().live))

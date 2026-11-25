"""Check async actions with replay or N4 Pro input. See async_actions.md."""

import argparse
import asyncio
import logging
import sys
from asyncio import sleep
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import TextIO

from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.host import AsyncHost, DispatchEvent
from opendeck.model import Result, Slot, Status

A_DELAY_SECONDS = 4
_LOGGER = logging.getLogger(__name__)


def button_label(slot: Slot, number: int) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (112, 112), "#172434")
    draw = ImageDraw.Draw(image)
    draw.text((56, 46), slot, anchor="mm", font_size=68, fill="white")
    draw.text((56, 93), str(number), anchor="mm", font_size=22, fill="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class SlowAction:
    def __init__(self, delay: int) -> None:
        self._delay = delay

    async def run(self) -> Result:
        await sleep(self._delay)
        return Result(Status.DONE)


class QuickAction:
    async def run(self) -> Result:
        return Result(Status.DONE)


def format_dispatch(event: DispatchEvent) -> str:
    phase: str = event.phase
    if phase == "finished" and event.result is not None:
        phase = event.result.status.value
    detail = f" ({event.result.detail})" if event.result and event.result.detail else ""
    return f"#{event.sequence} {event.slot} {phase}{detail}"


async def main(
    live: bool, *, a_delay: int = A_DELAY_SECONDS, debug: bool = False
) -> None:
    def write_line(message: str, *, file: TextIO | None = None) -> None:
        if debug:
            _LOGGER.debug("%s", message)
        else:
            print(message, file=file, flush=True)

    a, b = Slot("A"), Slot("B")
    keys = {1: a, 2: b}
    if live:
        write_line("Preparing N4 Pro. Wait for INPUT OK.", file=sys.stderr)
        from opendeck.adapters.streamdock import StreamDockFactory

        sdk = Path(__file__).resolve().parents[1] / "vendor" / "streamdock-sdk"
        product = StreamDockFactory(keys, (), sdk).make_surface(
            {slot: number for number, slot in keys.items()},
            initial_images={
                slot: button_label(slot, number) for number, slot in keys.items()
            },
        )
    else:
        events = tuple(
            Edge(key, pressed) for key in (1, 1, 1, 1, 2) for pressed in (True, False)
        )
        product = ReplayFactory(keys, (), events).make()
    try:
        product.link.open()
        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(
                tasks,
                pending_limit=2,
                trace=lambda event: write_line(format_dispatch(event)),
            )
            host.bind(SlowAction(a_delay), [a])
            host.bind(QuickAction(), [b])
            if live:
                await host.listen(
                    product.input,
                    product.subject,
                    on_ready=lambda: write_line("INPUT OK"),
                )
            else:
                write_line("Replay: running A, A, A, A, B once.", file=sys.stderr)
                while (slot := product.input.take()) is not None:
                    host.dispatch(slot)
    finally:
        product.link.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="read an N4 Pro until Ctrl+C"
    )
    parser.add_argument(
        "--a-delay",
        type=int,
        default=A_DELAY_SECONDS,
        metavar="SECONDS",
        help="set how long A runs (default: %(default)s seconds)",
    )
    parser.add_argument(
        "--debug", action="store_true", help="log timestamped input and action events"
    )
    args = parser.parse_args()
    if args.a_delay <= 0:
        parser.error("--a-delay must be positive")
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(threadName)s %(name)s %(message)s",
        )
    with suppress(KeyboardInterrupt):
        asyncio.run(main(args.live, a_delay=args.a_delay, debug=args.debug))

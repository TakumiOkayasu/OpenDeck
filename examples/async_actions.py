"""Replay A, A, B. B resumes the first A. The second A runs last."""

import argparse
import asyncio
import sys
from contextlib import suppress
from pathlib import Path

from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.host import AsyncHost
from opendeck.model import Result, Slot, Status


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
        print(slot, result.status.value if result else "unassigned")

    keys = {1: a, 2: b}
    if live:
        from opendeck.adapters.streamdock import StreamDockFactory

        sdk = Path(__file__).resolve().parents[1] / "vendor" / "streamdock-sdk"
        product = StreamDockFactory(keys, (), sdk).make()
    else:
        events = tuple(Edge(k, down) for k in (1, 1, 2) for down in (True, False))
        product = ReplayFactory(keys, (), events).make()
    try:
        product.link.open()
        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, report, pending_limit=2)
            host.bind(ReadState(), [a])
            host.bind(Resume(), [b])
            if live:
                print(
                    "Live: N4 Pro input only. Release buttons 1, 1, 2. Ctrl+C to exit.",
                    file=sys.stderr,
                    flush=True,
                )
                await host.listen(product.input, product.subject)
            else:
                print("Replay: running A, A, B once.", file=sys.stderr, flush=True)
                while (slot := product.input.take()) is not None:
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

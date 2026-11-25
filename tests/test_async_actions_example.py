import asyncio
import runpy
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from test_streamdock import FakeManager
from test_surface import DisplayDevice

from opendeck.adapters import streamdock

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "async_actions.py"


@asynccontextmanager
async def live_sample(monkeypatch, main):
    device = DisplayDevice()
    sdk = streamdock._Sdk(FakeManager([device]), DisplayDevice, "button")
    monkeypatch.setattr(streamdock, "_load", lambda _: sdk)
    lines: asyncio.Queue[str] = asyncio.Queue()
    monkeypatch.setitem(
        main.__globals__, "print", lambda line, **_: lines.put_nowait(line)
    )

    def press(key):
        device.emit_packet(key, 1)
        device.emit_packet(key, 0)

    async def expect(line):
        try:
            actual = await asyncio.wait_for(lines.get(), 8)
        except TimeoutError:
            raise AssertionError(f"No sample output for {line!r}") from None
        assert actual == line

    live = asyncio.create_task(main(True))
    try:
        assert (await asyncio.wait_for(lines.get(), 3)).startswith("Live: N4 Pro.")
        yield press, expect
    finally:
        live.cancel()
        with suppress(asyncio.CancelledError):
            await live
    assert device.closed == [False]


def test_a_completes_without_pressing_b(monkeypatch):
    main = runpy.run_path(str(SCRIPT))["main"]

    async def check():
        async with live_sample(monkeypatch, main) as (press, expect):
            press(1)
            await expect("#1 A accepted")
            await expect("#1 A done")

    asyncio.run(check())


def test_b_completes_while_a_is_busy_and_each_a_completion_frees_a_slot(monkeypatch):
    main = runpy.run_path(str(SCRIPT))["main"]

    async def check():
        running: asyncio.Queue[asyncio.Event] = asyncio.Queue()

        async def wait_for_operation(_seconds):
            finished = asyncio.Event()
            running.put_nowait(finished)
            await finished.wait()

        monkeypatch.setitem(main.__globals__, "sleep", wait_for_operation)
        async with live_sample(monkeypatch, main) as (press, expect):
            press(1)
            await expect("#1 A accepted")
            first = await asyncio.wait_for(running.get(), 3)
            press(1)
            await expect("#2 A accepted")
            press(1)
            await expect("#3 A rejected (action queue full)")

            press(2)
            await expect("#4 B accepted")
            await expect("#4 B done")
            first.set()
            await expect("#1 A done")
            second = await asyncio.wait_for(running.get(), 3)

            press(1)
            await expect("#5 A accepted")
            second.set()
            await expect("#2 A done")
            third = await asyncio.wait_for(running.get(), 3)
            third.set()
            await expect("#5 A done")

    asyncio.run(check())

import asyncio
import runpy
from contextlib import suppress
from pathlib import Path

from test_streamdock import FakeManager
from test_surface import DisplayDevice

from opendeck.adapters import streamdock

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "async_actions.py"


def test_live_sample_reports_admission_and_completion_with_the_same_input_number(
    monkeypatch,
):
    """Before B, identify accepted and rejected A inputs individually."""
    main = runpy.run_path(str(SCRIPT))["main"]
    device = DisplayDevice()
    sdk = streamdock._Sdk(FakeManager([device]), DisplayDevice, "button")
    monkeypatch.setattr(streamdock, "_load", lambda _: sdk)

    async def check():
        lines: asyncio.Queue[str] = asyncio.Queue()
        monkeypatch.setitem(
            main.__globals__, "print", lambda line, **_: lines.put_nowait(line)
        )

        def release(key):
            device.emit_packet(key, 1)
            device.emit_packet(key, 0)

        async def expect(line):
            try:
                actual = await asyncio.wait_for(lines.get(), 3)
            except TimeoutError:
                raise AssertionError(f"No sample output for {line!r}") from None
            assert actual == line

        live = asyncio.create_task(main(True))
        try:
            assert (await asyncio.wait_for(lines.get(), 3)).startswith("Live: N4 Pro.")
            for number in (1, 2):
                release(1)
                await expect(f"#{number} A accepted")
            for number in (3, 4):
                release(1)
                await expect(f"#{number} A rejected (action queue full)")
            release(2)
            await expect("#5 B accepted")
            await expect("#5 B done")
            await expect("#1 A done")
            await expect("#2 A done")
            release(1)
            await expect("#6 A accepted")
            await expect("#6 A done")
            assert lines.empty()
        finally:
            live.cancel()
            with suppress(asyncio.CancelledError):
                await live
        assert device.closed == [False]

    asyncio.run(check())

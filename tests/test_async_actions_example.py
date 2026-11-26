import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

from opendeck.adapters import streamdock
from opendeck.model import Slot

spec = spec_from_file_location(
    "async_actions_example",
    Path(__file__).resolve().parents[1] / "examples" / "async_actions.py",
)
assert spec is not None and spec.loader is not None
example = module_from_spec(spec)
spec.loader.exec_module(example)


@pytest.mark.parametrize("close_fails", [False, True])
def test_timed_live_sample_unsubscribes_and_closes_without_input(
    monkeypatch, capsys, close_fails
):
    calls = []
    slots = iter([Slot("A"), None])

    def close():
        calls.append("close")
        if close_fails:
            raise OSError("close failed")

    product = SimpleNamespace(
        link=SimpleNamespace(open=lambda: calls.append("open"), close=close),
        input=SimpleNamespace(take=lambda: next(slots)),
        subject=SimpleNamespace(
            add=lambda _: calls.append("add"), remove=lambda _: calls.append("remove")
        ),
    )
    monkeypatch.setattr(
        streamdock,
        "StreamDockFactory",
        lambda *_: SimpleNamespace(make_surface=lambda _: product),
    )

    run = asyncio.wait_for(example.main(True, live_seconds=0.02), 2)
    expected = ["sample ready", "link close started"]
    if close_fails:
        with pytest.raises(OSError, match="close failed"):
            asyncio.run(run)
    else:
        asyncio.run(run)
        expected.append("link closed")

    assert calls == ["open", "add", "remove", "close"]
    phases = [line.split(" ", 1)[1] for line in capsys.readouterr().err.splitlines()]
    assert phases == expected

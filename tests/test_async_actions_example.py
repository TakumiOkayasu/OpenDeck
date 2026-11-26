import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opendeck.adapters import streamdock
from opendeck.host import Assignment, UnboundError
from opendeck.model import Slot
from opendeck.ports import Input, Link, Subject, SurfaceProduct, View

spec = spec_from_file_location(
    "async_actions_example",
    Path(__file__).resolve().parents[1] / "examples" / "async_actions.py",
)
assert spec is not None and spec.loader is not None
example = module_from_spec(spec)
spec.loader.exec_module(example)


@pytest.mark.parametrize("close_fails", [False, True])
def test_timed_live_sample_releases_observer_and_views_before_closing(
    monkeypatch, capsys, close_fails
):
    calls = []
    assigned_views = []
    images = {Slot(name): Mock(spec=View) for name in ("A", "B")}
    for slot, view in images.items():
        view.draw.side_effect = lambda _image, slot=slot: calls.append(f"draw {slot}")

    get_view = Assignment.view

    def remember_view(assignment, name):
        view = get_view(assignment, name)
        assigned_views.append(view)
        return view

    monkeypatch.setattr(Assignment, "view", remember_view)

    def close():
        calls.append("close")
        assert len(assigned_views) == 2
        for view in assigned_views:
            with pytest.raises(UnboundError):
                view.draw(b"stale")
        if close_fails:
            raise OSError("close failed")

    link = Mock(spec=Link)
    link.open.side_effect = lambda: calls.append("open")
    link.close.side_effect = close
    input_source = Mock(spec=Input)
    input_source.take.side_effect = [Slot("A"), None]
    subject = Mock(spec=Subject)
    subject.add.side_effect = lambda _: calls.append("add")
    subject.remove.side_effect = lambda _: calls.append("remove")
    product = SurfaceProduct(
        link=link,
        input=input_source,
        subject=subject,
        touch=Mock(spec=Input),
        touch_subject=Mock(spec=Subject),
        images=images,
        screen=Mock(spec=View),
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

    assert calls == ["open", "draw A", "draw B", "add", "remove", "close"]
    phases = [line.split(" ", 1)[1] for line in capsys.readouterr().err.splitlines()]
    assert phases == expected

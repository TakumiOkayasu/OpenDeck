from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path

from PIL import Image

spec = spec_from_file_location(
    "n4pro_display_diagnostic",
    Path(__file__).resolve().parents[1] / "tools" / "n4pro_display_diagnostic.py",
)
assert spec is not None and spec.loader is not None
diagnostic = module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def test_diagnostic_guides_swipes_in_japanese_with_physical_directions():
    from unittest.mock import patch

    prompts = []
    steps = []
    with (
        patch("builtins.input", side_effect=lambda prompt: prompts.append(prompt)),
        patch.object(
            diagnostic,
            "capture_step",
            side_effect=lambda _, __, step, ___: steps.append(step),
        ),
    ):
        diagnostic.record_inputs(None, None)
    assert any("右から左" in prompt and "←" in prompt for prompt in prompts)
    assert any("左から右" in prompt and "→" in prompt for prompt in prompts)
    assert all("Enter" in prompt for prompt in prompts)
    assert "swipe_left" in steps and "swipe_right" in steps


def test_images_distinguish_each_target_and_screen():
    images = [diagnostic.make_image(str(n), (176, 112)) for n in range(11, 15)]
    assert len(set(images)) == 4
    for image in images:
        with Image.open(BytesIO(image)) as decoded:
            assert decoded.size == (176, 112)
            assert decoded.mode == "RGBA"
    with Image.open(BytesIO(diagnostic.make_image("BG", (800, 480)))) as decoded:
        assert decoded.size == (800, 480)


def test_drawing_targets_do_not_define_input_numbering():
    assert diagnostic.targets() == {f"display-{n}": n for n in range(1, 15)}


def test_diagnostic_closes_connection_when_interrupted(monkeypatch, tmp_path):
    import sys
    from types import ModuleType, SimpleNamespace

    drawn = []
    closed = []

    class Source:
        def __init__(self, value):
            self.values = iter([value, None])

        def take(self):
            return next(self.values)

    class View:
        def draw(self, image):
            drawn.append(image)

    product = SimpleNamespace(
        link=SimpleNamespace(open=lambda: None, close=lambda: closed.append(True)),
        images={name: View() for name in diagnostic.targets()},
        screen=View(),
        input=Source("input-3"),
        touch=Source("point"),
    )

    class Factory:
        def __init__(self, keys, chords, sdk, index):
            assert keys[3] == "input-3"
            assert chords == ()

        def make_surface(self, images):
            assert images["display-3"] == 3
            return product

    opendeck = ModuleType("opendeck")
    opendeck.Slot = str
    adapter = ModuleType("opendeck.adapters.streamdock")
    adapter.StreamDockFactory = Factory
    monkeypatch.setitem(sys.modules, "opendeck", opendeck)
    monkeypatch.setitem(
        sys.modules, "opendeck.adapters", ModuleType("opendeck.adapters")
    )
    monkeypatch.setitem(sys.modules, "opendeck.adapters.streamdock", adapter)
    monkeypatch.setattr(
        sys, "argv", ["diagnostic", "--output", str(tmp_path / "out.jsonl")]
    )
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(
        diagnostic, "record_inputs", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    diagnostic.main()
    assert len(drawn) == 15
    assert closed == [True]


def test_connection_is_closed_if_drawing_fails(monkeypatch):
    from io import StringIO as BytesIOText
    from types import SimpleNamespace

    import pytest

    closed = []

    class BrokenView:
        def draw(self, image):
            raise RuntimeError("transfer failed")

    product = SimpleNamespace(
        link=SimpleNamespace(open=lambda: None, close=lambda: closed.append(True)),
        screen=BrokenView(),
    )
    monkeypatch.setattr("builtins.input", lambda _: "")
    with pytest.raises(RuntimeError, match="transfer failed"):
        diagnostic.run(product, {}, BytesIOText())
    assert closed == [True]


def test_guided_capture_writes_structured_events_with_operation(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    class Source:
        def __init__(self, values):
            self.values = iter(values)

        def take(self):
            return next(self.values, None)

    product = SimpleNamespace(
        input=Source([None, "input-3", None]),
        touch=Source([None, SimpleNamespace(x=12, y=34), None]),
    )
    path = tmp_path / "result.jsonl"
    clock = iter([0, 0, 2])
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(diagnostic.time, "sleep", lambda _: None)
    with path.open("x", encoding="utf-8") as output:
        diagnostic.capture_step(product, output, "touch_top_left", 1)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["type"] == "step_start"
    assert rows[1]["type"] == "button"
    assert rows[1]["slot"] == "input-3"
    assert rows[2]["type"] == "touch"
    assert (rows[2]["x"], rows[2]["y"]) == (12, 34)
    assert all(row["step"] == "touch_top_left" for row in rows)
    assert rows[-1]["type"] == "step_end"


def test_pending_events_are_not_attributed_to_next_step(monkeypatch):
    import json
    from io import StringIO
    from types import SimpleNamespace

    class Source:
        def __init__(self, values):
            self.values = iter(values)

        def take(self):
            return next(self.values, None)

    product = SimpleNamespace(
        input=Source(["input-2", None]),
        touch=Source([None, SimpleNamespace(direction="left"), None]),
    )
    output = StringIO()
    clock = iter([0, 0, 2])
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(diagnostic.time, "sleep", lambda _: None)
    diagnostic.capture_step(product, output, "swipe_left", 1)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[0]["slot"] == "input-2"
    assert rows[0]["step"] is None
    assert rows[2]["type"] == "swipe"
    assert rows[2]["direction"] == "left"
    assert rows[2]["step"] == "swipe_left"

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


def test_diagnostic_records_input_and_closes_connection(monkeypatch, capsys):
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
    monkeypatch.setattr(sys, "argv", ["diagnostic"])
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(
        diagnostic.time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    diagnostic.main()
    output = capsys.readouterr().out
    assert "input 'input-3'" in output
    assert "touch 'point'" in output
    assert len(drawn) == 15
    assert closed == [True]


def test_connection_is_closed_if_drawing_fails(monkeypatch):
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
        diagnostic.run(product, {})
    assert closed == [True]

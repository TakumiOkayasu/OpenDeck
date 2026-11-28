from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

spec = spec_from_file_location(
    "n4pro_display_diagnostic",
    Path(__file__).resolve().parents[1] / "tools" / "n4pro_display_diagnostic.py",
)
assert spec is not None and spec.loader is not None
diagnostic = module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def test_callback_logging_keeps_receipt_metadata_and_restores_logger():
    import json
    import logging
    from io import StringIO

    logger = logging.getLogger("opendeck.adapters.streamdock")
    level = logger.level
    handlers = list(logger.handlers)
    output = StringIO()
    with diagnostic.observe_sdk(output):
        logger.debug("ordinary debug message")
        for kind, received in (("sdk_raw", 123), ("sdk_decoded", 124)):
            logger.debug(
                "callback",
                extra={
                    "diagnostic": {
                        "kind": kind,
                        "packet_id": 7,
                        "generation": 1,
                        "received_monotonic_ns": received,
                    }
                },
            )

    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [row["type"] for row in rows] == ["sdk_raw", "sdk_decoded"]
    assert [row["observation_sequence"] for row in rows] == [1, 2]
    assert [row["received_monotonic_ns"] for row in rows] == [123, 124]
    assert all(row["packet_id"] == 7 for row in rows)
    assert all(row["monotonic_ns"] > 0 for row in rows)
    assert logger.level == level
    assert logger.handlers == handlers


def install_factory(monkeypatch, factory):
    import sys
    from types import ModuleType

    opendeck = ModuleType("opendeck")
    adapter = ModuleType("opendeck.adapters.streamdock")
    monkeypatch.setattr(opendeck, "Slot", str, raising=False)
    monkeypatch.setattr(adapter, "StreamDockFactory", factory, raising=False)
    monkeypatch.setitem(sys.modules, "opendeck", opendeck)
    monkeypatch.setitem(
        sys.modules, "opendeck.adapters", ModuleType("opendeck.adapters")
    )
    monkeypatch.setitem(sys.modules, "opendeck.adapters.streamdock", adapter)


def test_log_write_failure_is_raised_on_owner_after_callback_returns():
    import logging
    from io import StringIO

    import pytest

    class FailedOutput(StringIO):
        def write(self, text):
            raise OSError("disk full")

    callback_returned = []
    logger = logging.getLogger("opendeck.adapters.streamdock")
    handlers = list(logger.handlers)
    level = logger.level
    with (
        pytest.raises(OSError, match="disk full"),
        diagnostic.observe_sdk(FailedOutput()),
    ):
        logger.debug("raw", extra={"diagnostic": {"kind": "sdk_raw"}})
        callback_returned.append(True)
    assert callback_returned == [True]
    assert logger.handlers == handlers
    assert logger.level == level


def test_closed_log_handler_ignores_a_previously_dispatched_callback():
    import logging
    from io import StringIO

    output = StringIO()
    logger = logging.getLogger("opendeck.adapters.streamdock")
    with diagnostic.observe_sdk(output):
        handler = logger.handlers[-1]
    output.close()
    record = logging.makeLogRecord({"diagnostic": {"kind": "sdk_raw"}})

    handler.handle(record)

    assert handler.sequence == 0


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


def test_selected_input_steps_run_without_drawing(monkeypatch):
    from io import StringIO
    from types import SimpleNamespace

    prompts = []
    steps = []
    closed = []
    product = SimpleNamespace(
        link=SimpleNamespace(open=lambda: None, close=lambda: closed.append(True))
    )
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt))
    monkeypatch.setattr(diagnostic, "draw_images", lambda *_: None)
    monkeypatch.setattr(
        diagnostic,
        "capture_step",
        lambda _, __, step, seconds: steps.append((step, seconds)),
    )

    diagnostic.run(product, {}, StringIO(), ("touch_center", "button_3"), 2)

    assert steps == [("touch_center", 2), ("button_3", 2)]
    assert len(prompts) == 2
    assert "中央" in prompts[0]
    assert "ボタン3" in prompts[1]
    assert closed == [True]


def test_capture_prompt_uses_the_selected_duration(monkeypatch, capsys):
    from io import StringIO

    monkeypatch.setattr(diagnostic, "drain_inputs", lambda *_: None)
    clock = iter([0, 3])
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: next(clock))

    diagnostic.capture_step(None, StringIO(), "touch_center", 2)

    assert "(2秒間)" in capsys.readouterr().out


def test_optional_hardware_steps_keep_the_original_default_sequence(monkeypatch):
    prompts = []
    captured = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt))
    monkeypatch.setattr(
        diagnostic, "capture_step", lambda _, __, step, ___: captured.append(step)
    )

    diagnostic.record_inputs(None, None)

    assert captured == [
        "touch_top_left",
        "touch_top_right",
        "touch_center",
        "touch_bottom_left",
        "touch_bottom_right",
        "swipe_left",
        "swipe_right",
        *[f"button_{number}" for number in range(1, 11)],
    ]
    captured.clear()
    prompts.clear()
    selected = (
        "knob_1_press_release",
        "knob_2_left",
        "knob_3_right",
        "knob_4_held_right",
        "secondary_2",
        "touch_hold",
        "touch_drag",
        "touch_two_fingers",
    )
    diagnostic.record_inputs(None, None, selected)
    assert captured == list(selected)
    assert "押して" in prompts[0] and "離す" in prompts[0]
    assert "反時計回り" in prompts[1]
    assert "時計回り" in prompts[2]
    assert "押したまま" in prompts[3]
    assert "左から" in prompts[4]
    assert "2本" in prompts[-1]


def test_cli_accepts_optional_knob_secondary_and_touch_steps(monkeypatch):
    import sys

    for number in range(1, 5):
        for operation in ("press_release", "left", "right", "held_left", "held_right"):
            name = f"knob_{number}_{operation}"
            monkeypatch.setattr(sys, "argv", ["diagnostic", "--step", name])
            assert diagnostic.parse_args().step == [name]
        name = f"secondary_{number}"
        monkeypatch.setattr(sys, "argv", ["diagnostic", "--step", name])
        assert diagnostic.parse_args().step == [name]
    for name in ("touch_hold", "touch_drag", "touch_two_fingers"):
        monkeypatch.setattr(sys, "argv", ["diagnostic", "--step", name])
        assert diagnostic.parse_args().step == [name]


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("background-images-background", ["background", "display-3", "background"]),
        ("images-background", ["display-3", "background"]),
    ],
)
def test_image_order_probe_records_each_phase_without_input_sampling(
    monkeypatch, order, expected
):
    import json
    from io import StringIO
    from types import SimpleNamespace

    drawn = []
    inputs = []
    closed = []
    product = SimpleNamespace(
        link=SimpleNamespace(open=lambda: None, close=lambda: closed.append(True)),
        screen=SimpleNamespace(draw=lambda _: drawn.append("background")),
        images={"display-3": SimpleNamespace(draw=lambda _: drawn.append("display-3"))},
    )
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(diagnostic, "record_inputs", lambda *_: inputs.append(True))
    output = StringIO()

    diagnostic.run(product, {"display-3": 3}, output, (), 5, order)

    assert drawn == expected
    assert inputs == []
    assert closed == [True]
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    phases = [row for row in rows if row["type"] == "image_phase_start"]
    assert [row["operation"] for row in phases] == order.split("-")
    assert [row["phase"] for row in phases] == list(range(1, len(expected) + 1))
    ends = [row for row in rows if row["type"] == "image_phase_end"]
    assert [row["phase"] for row in ends] == [row["phase"] for row in phases]


def test_main_passes_only_selected_steps_and_duration(monkeypatch, tmp_path):
    import json
    import sys
    from types import SimpleNamespace

    install_factory(
        monkeypatch, lambda *args: SimpleNamespace(make_surface=lambda _: "surface")
    )
    path = tmp_path / "selected.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        ["diagnostic", "--step", "button_3", "--seconds", "2", "--output", str(path)],
    )
    calls = []
    monkeypatch.setattr(diagnostic, "run", lambda *args: calls.append(args))

    diagnostic.main()

    assert calls[0][0] == "surface"
    assert calls[0][3:] == (("button_3",), 2, None)
    session = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert session["steps"] == ["button_3"]
    assert session["capture_seconds"] == 2


def test_main_selects_image_order_probe(monkeypatch, tmp_path):
    import json
    import sys
    from types import SimpleNamespace

    install_factory(
        monkeypatch, lambda *args: SimpleNamespace(make_surface=lambda _: "surface")
    )
    path = tmp_path / "images.jsonl"
    order = "images-background"
    monkeypatch.setattr(
        sys, "argv", ["diagnostic", "--image-order", order, "--output", str(path)]
    )
    calls = []
    monkeypatch.setattr(diagnostic, "run", lambda *args: calls.append(args))

    diagnostic.main()

    assert calls[0][3:] == ((), 5, order)
    session = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert session["image_order"] == order


def test_image_order_and_input_step_are_separate_modes(monkeypatch, capsys):
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnostic",
            "--image-order",
            "images-background",
            "--step",
            "knob_1_left",
        ],
    )
    with pytest.raises(SystemExit) as error:
        diagnostic.parse_args()
    assert error.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_optional_step_keeps_raw_only_observations(monkeypatch):
    import json
    import logging
    import sys
    from io import StringIO
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules, "opendeck", SimpleNamespace(TouchPoint=type("Point", (), {}))
    )
    empty = SimpleNamespace(take=lambda: None)
    product = SimpleNamespace(input=empty, touch=empty)
    clock = iter([0, 0, 2])
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: next(clock))
    logger = logging.getLogger("opendeck.adapters.streamdock")
    packet = {"diagnostic": {"kind": "sdk_raw", "raw": "abcd"}}
    monkeypatch.setattr(
        diagnostic.time, "sleep", lambda _: logger.debug("unknown raw", extra=packet)
    )
    output = StringIO()

    with diagnostic.observe_sdk(output):
        diagnostic.capture_step(product, output, "knob_1_held_left", 1)

    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [row["type"] for row in rows] == ["step_start", "sdk_raw", "step_end"]
    assert rows[0]["step"] == rows[-1]["step"] == "knob_1_held_left"
    assert rows[1]["raw"] == "abcd"


def test_capture_duration_rejects_nonpositive_and_nonfinite_values(monkeypatch, capsys):
    import sys

    import pytest

    for seconds in ("0", "-1", "nan", "inf"):
        monkeypatch.setattr(sys, "argv", ["diagnostic", f"--seconds={seconds}"])
        with pytest.raises(SystemExit) as error:
            diagnostic.parse_args()
        assert error.value.code == 2
        assert (
            "--seconds must be finite and greater than zero" in capsys.readouterr().err
        )


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


def test_drawing_records_the_elapsed_time_for_each_returned_call(monkeypatch):
    import json
    from io import StringIO
    from types import SimpleNamespace

    clock = iter([1_000_000, 3_500_000, 8_000_000, 9_000_000])
    monkeypatch.setattr(diagnostic.time, "perf_counter_ns", lambda: next(clock))
    monkeypatch.setattr("builtins.input", lambda _: "")
    view = SimpleNamespace(draw=lambda _: None)
    product = SimpleNamespace(screen=view, images={"display-3": view})
    output = StringIO()

    diagnostic.draw_images(product, {"display-3": 3}, output)

    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [
        (row["type"], row["target"], row["label"], row["elapsed_ms"]) for row in rows
    ] == [
        ("image_sent", "background", "BG", 2.5),
        ("image_sent", "display-3", "D3", 1.0),
    ]


def test_default_log_directory_is_created_on_first_run(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    install_factory(
        monkeypatch,
        lambda *args: SimpleNamespace(make_surface=lambda _: object()),
    )
    monkeypatch.setattr(sys, "argv", ["diagnostic"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(diagnostic, "run", lambda *_: None)
    diagnostic.main()
    assert len(list((tmp_path / "logs/diagnostics").glob("*.jsonl"))) == 1


def test_diagnostic_closes_connection_when_interrupted(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    drawn = []
    closed = []

    class View:
        def draw(self, image):
            drawn.append(image)

    product = SimpleNamespace(
        link=SimpleNamespace(open=lambda: None, close=lambda: closed.append(True)),
        images={name: View() for name in diagnostic.targets()},
        screen=View(),
    )

    class Factory:
        def __init__(self, keys, chords, sdk, index):
            assert keys[3] == "input-3"
            assert chords == ()

        def make_surface(self, images):
            assert images["display-3"] == 3
            return product

    install_factory(monkeypatch, Factory)
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
    import json
    from io import StringIO
    from types import SimpleNamespace

    import pytest

    closed = []

    class BrokenView:
        def draw(self, image):
            raise RuntimeError("transfer failed")

    product = SimpleNamespace(
        link=SimpleNamespace(open=lambda: None, close=lambda: closed.append(True)),
        screen=SimpleNamespace(draw=lambda _: None),
        images={"display-3": BrokenView()},
    )
    clock = iter([1_000_000, 2_000_000, 5_000_000, 8_250_000])
    monkeypatch.setattr(diagnostic.time, "perf_counter_ns", lambda: next(clock))
    monkeypatch.setattr("builtins.input", lambda _: "")
    output = StringIO()
    with pytest.raises(RuntimeError, match="transfer failed"):
        diagnostic.run(product, {"display-3": 3}, output)
    assert closed == [True]
    sent, failed, error = [json.loads(line) for line in output.getvalue().splitlines()]
    assert sent["type"] == "image_sent"
    assert failed["type"] == "image_failed"
    assert failed["target"] == "display-3"
    assert failed["label"] == "D3"
    assert failed["elapsed_ms"] == 3.25
    assert error["type"] == "error"
    assert "RuntimeError: transfer failed" in error["traceback"]


def test_diagnostic_reports_success_after_closing(monkeypatch, capsys):
    import json
    from io import StringIO
    from types import SimpleNamespace

    closed = []
    product = SimpleNamespace(
        link=SimpleNamespace(open=lambda: None, close=lambda: closed.append(True))
    )
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(diagnostic, "draw_images", lambda *_: None)
    monkeypatch.setattr(diagnostic, "record_inputs", lambda *_: None)
    output = StringIO()
    diagnostic.run(product, {}, output)
    assert closed == [True]
    assert json.loads(output.getvalue().splitlines()[-1])["type"] == "finished"
    assert "正常に終了" in capsys.readouterr().out


def test_guided_capture_writes_structured_events_with_operation(tmp_path, monkeypatch):
    import json
    import sys
    from types import SimpleNamespace

    class TouchPoint(SimpleNamespace):
        pass

    monkeypatch.setitem(sys.modules, "opendeck", SimpleNamespace(TouchPoint=TouchPoint))

    class Source:
        def __init__(self, values):
            self.values = iter(values)

        def take(self):
            return next(self.values, None)

    product = SimpleNamespace(
        input=Source([None, "input-3", None]),
        touch=Source([None, TouchPoint(x=12, y=34), None]),
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
    import sys
    from io import StringIO
    from types import SimpleNamespace

    class TouchPoint:
        pass

    monkeypatch.setitem(sys.modules, "opendeck", SimpleNamespace(TouchPoint=TouchPoint))

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

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from test_streamdock import FakeManager, FakeN4Pro, input_packet

import opendeck
from opendeck.adapters import streamdock
from opendeck.adapters.streamdock import StreamDockError, StreamDockFactory
from opendeck.model import Slot
from opendeck.runtime import drain


class DisplayDevice(FakeN4Pro):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[tuple[int, bytes]] = []
        self.frames: list[bytes] = []
        self.touch_callback = None
        self.key_result: object = 0
        self.background_result: int | None = None

    def set_key_image(self, key: int, image: BytesIO) -> object:
        self.images.append((key, image.read()))
        return self.key_result

    def set_frame_background(self, image: BytesIO) -> int | None:
        self.frames.append(image.read())
        return self.background_result

    def set_touchscreen_callback(self, callback) -> None:
        self.touch_callback = callback


def surface(device: DisplayDevice, **options):
    sdk = streamdock._Sdk(FakeManager([device]), DisplayDevice, "button")
    with patch.object(streamdock, "_load", return_value=sdk):
        factory = StreamDockFactory({1: Slot("a")}, (), Path("sdk-checkout"))
        return factory.make_surface({Slot("a"): 1, Slot("panel"): 11}, **options)


def button_surface(device: DisplayDevice, **options):
    sdk = streamdock._Sdk(FakeManager([device]), DisplayDevice, "button")
    with patch.object(streamdock, "_load", return_value=sdk):
        factory = StreamDockFactory({1: Slot("a")}, (), Path("sdk-checkout"))
        return factory.make_button_surface({Slot("a"): 1}, **options)


def test_button_state_and_images_share_one_connection():
    device = DisplayDevice()
    ticks = iter((1.0, 2.0))
    product = button_surface(device, clock=lambda: next(ticks))
    button = product.buttons[Slot("a")]
    product.link.open()
    try:
        device.emit_packet(1, 1)
        assert button.read() is True
        product.images[Slot("a")].draw(b"pressed")
        device.emit_packet(1, 0)
        assert button.read() is False
        assert button.take() == opendeck.Change(True, 1.0)
        assert button.take() == opendeck.Change(False, 2.0)
        assert button.take() is None
        assert device.images == [(11, b"pressed")]
        assert device.opened == 1
        assert device.initialized == 1
    finally:
        product.link.close()
    assert device.closed == [False]


def test_closing_shared_connection_invalidates_all_capabilities():
    device = DisplayDevice()
    product = button_surface(device)
    product.link.open()
    device.emit_packet(1, 1)
    product.link.close()
    button = product.buttons[Slot("a")]
    for operation in (button.read, button.take, product.touch.take):
        with pytest.raises(opendeck.InputError):
            operation()
    with pytest.raises(StreamDockError):
        product.screen.draw(b"closed")
    assert device.callback is None
    assert device.raw_callback is None
    assert device.touch_callback is None


def test_shared_connection_input_failure_invalidates_all_capabilities():
    device = DisplayDevice()
    product = button_surface(device)
    product.link.open()
    try:
        device.emit_packet(1, 1)
        assert device.touch_callback is not None
        device.touch_callback(device, SimpleNamespace(x="invalid", y=0))
        button = product.buttons[Slot("a")]
        for operation in (button.read, button.take, product.touch.take):
            with pytest.raises(opendeck.InputError):
                operation()
        with pytest.raises(StreamDockError):
            product.images[Slot("a")].draw(b"failed")
    finally:
        product.link.close()


def test_shared_connection_initial_image_failure_releases_the_device():
    device = DisplayDevice()
    device.key_result = -1
    product = button_surface(device, initial_images={Slot("a"): b"initial"})
    with pytest.raises(StreamDockError, match="draw image"):
        product.link.open()
    assert device.opened == 1
    assert device.closed == [False]
    assert device.callback is None
    assert device.raw_callback is None
    assert device.touch_callback is None
    with pytest.raises(opendeck.InputError):
        product.buttons[Slot("a")].read()


def test_shared_connection_display_preparation_failure_releases_the_device():
    device = DisplayDevice()

    def prepare_display():
        raise RuntimeError("display preparation failed")

    product = button_surface(device, prepare_display=prepare_display)
    with pytest.raises(RuntimeError, match="display preparation failed"):
        product.link.open()
    assert device.opened == 1
    assert device.closed == [False]
    assert device.callback is None
    assert device.raw_callback is None
    assert device.touch_callback is None
    with pytest.raises(opendeck.InputError):
        product.touch.take()


def test_images_use_distinct_display_slots_and_share_the_connection():
    device = DisplayDevice()
    product = surface(device)
    with pytest.raises(StreamDockError):
        product.images[Slot("a")].draw(b"image")
    product.link.open()
    try:
        product.images[Slot("a")].draw(b"button")
        product.images[Slot("panel")].draw(b"panel")
        product.screen.draw(b"screen")
        assert device.images == [(11, b"button"), (1, b"panel")]
        assert device.frames == [b"screen"]
        assert device.opened == 1
    finally:
        product.link.close()
    with pytest.raises(StreamDockError):
        product.screen.draw(b"screen")


def test_explicit_reopen_reapplies_initial_image_without_replaying_actions():
    device = DisplayDevice()
    slot = Slot("a")
    product = surface(device, initial_images={slot: b"initial"})
    calls = []

    class Record(opendeck.Action):
        def run(self) -> opendeck.Result:
            calls.append("run")
            return opendeck.Result(opendeck.Status.DONE)

    binding = opendeck.Binding({slot: Record()})
    product.link.open()
    try:
        device.emit_packet(1, 1)
        device.emit_packet(1, 0)
        assert drain(product.input, binding, lambda *_: None) == 1
        product.images[slot].draw(b"runtime")
        device.emit_packet(1, 1)
        device.emit_packet(1, 0)
    finally:
        product.link.close()

    product.link.open()
    try:
        assert drain(product.input, binding, lambda *_: None) == 0
        assert calls == ["run"]
        assert device.images == [(11, b"initial"), (11, b"runtime"), (11, b"initial")]
    finally:
        product.link.close()


@pytest.mark.parametrize(
    ("sdk_direction", "movement"),
    [("right", opendeck.Direction.LEFT), ("left", opendeck.Direction.RIGHT)],
)
@pytest.mark.parametrize("make_product", [surface, button_surface])
def test_touch_points_and_swipes_are_received_without_sdk_types(
    sdk_direction, movement, make_product
):
    device = DisplayDevice()
    product = make_product(device)
    with pytest.raises(opendeck.InputError):
        product.touch.take()
    product.link.open()
    try:
        assert device.touch_callback is not None
        device.touch_callback(device, SimpleNamespace(x=46, y=75))
        assert device.callback is not None
        device.callback(
            device,
            SimpleNamespace(
                event_type="swipe", direction=SimpleNamespace(value=sdk_direction)
            ),
        )
        assert product.touch.take() == opendeck.TouchPoint(46, 75)
        assert product.touch.take() == opendeck.Swipe(movement)
        assert product.touch.take() is None
    finally:
        product.link.close()
    with pytest.raises(opendeck.InputError):
        product.touch.take()
    assert device.touch_callback is None


def test_stale_swipe_does_not_discard_current_button_packet():
    device = DisplayDevice()
    product = surface(device)
    product.link.open()
    old_callback = device.callback
    assert old_callback is not None
    product.link.close()
    product.link.open()
    try:
        device.emit_raw(input_packet(1, 1))
        old_callback(
            device,
            SimpleNamespace(
                event_type="swipe", direction=SimpleNamespace(value="right")
            ),
        )
        device.emit(11, 1)
        device.emit_packet(1, 0)
        assert product.input.take() == Slot("a")
        assert product.touch.take() is None
    finally:
        product.link.close()


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (-1, "key image rejected"),
        (None, "key image transport result unavailable"),
        (0x04000201, "key image transport error 0x04000201"),
        (0xFF000000, "key image transport error 0xFF000000"),
        pytest.param(
            b"unexpected", "unexpected key image transport result", id="unexpected"
        ),
    ],
)
@pytest.mark.parametrize("make_product", [surface, button_surface])
def test_key_image_failure_identifies_reason_and_sdk_slot(result, reason, make_product):
    device = DisplayDevice()
    device.key_result = result
    product = make_product(device)
    expected = f"SDK could not draw image for SDK slot 11 ({reason})"
    product.link.open()
    try:
        with pytest.raises(StreamDockError) as error:
            product.images[Slot("a")].draw(b"image")
        assert str(error.value) == expected
    finally:
        product.link.close()


@pytest.mark.parametrize("make_product", [surface, button_surface])
def test_background_rejection_has_no_transport_status(make_product):
    device = DisplayDevice()
    device.background_result = -1
    product = make_product(device)
    expected = "SDK could not draw image (background image rejected)"
    product.link.open()
    try:
        with pytest.raises(StreamDockError) as error:
            product.screen.draw(b"image")
        assert str(error.value) == expected
    finally:
        product.link.close()


def test_touch_observer_can_be_registered_before_open():
    device = DisplayDevice()
    product = surface(device)
    notifications: list[str] = []

    class Observer(opendeck.Observer):
        def on_change(self) -> None:
            notifications.append("changed")

    observer = Observer()
    product.touch_subject.add(observer)
    assert notifications == []
    product.link.open()
    try:
        assert device.touch_callback is not None
        device.touch_callback(device, SimpleNamespace(x=1, y=2))
        assert notifications == ["changed"]
    finally:
        product.touch_subject.remove(observer)
        product.link.close()


def test_invalid_touch_coordinates_fail_input_instead_of_delivering_invalid_data():
    device = DisplayDevice()
    product = surface(device)
    product.link.open()
    try:
        assert device.touch_callback is not None
        device.touch_callback(device, SimpleNamespace(x="bad", y=75))
        with pytest.raises(opendeck.InputError):
            product.touch.take()
    finally:
        product.link.close()


def test_two_slots_cannot_alias_one_display_on_the_same_surface():
    device = DisplayDevice()
    with patch.object(
        streamdock,
        "_load",
        return_value=streamdock._Sdk(FakeManager([device]), DisplayDevice, "button"),
    ):
        factory = StreamDockFactory({}, (), Path("sdk-checkout"))
        with pytest.raises(ValueError, match="distinct"):
            factory.make_surface({Slot("left"): 1, Slot("right"): 1})
    assert device.opened == 0

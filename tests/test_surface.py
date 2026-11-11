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


class DisplayDevice(FakeN4Pro):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[tuple[int, bytes]] = []
        self.frames: list[bytes] = []
        self.touch_callback = None
        self.key_result: int | None = 0

    def set_key_image(self, key: int, image: BytesIO) -> int | None:
        self.images.append((key, image.read()))
        return self.key_result

    def set_frame_background(self, image: BytesIO) -> None:
        self.frames.append(image.read())

    def set_touchscreen_callback(self, callback) -> None:
        self.touch_callback = callback


def surface(device: DisplayDevice):
    sdk = streamdock._Sdk(FakeManager([device]), DisplayDevice, "button")
    with patch.object(streamdock, "_load", return_value=sdk):
        factory = StreamDockFactory({1: Slot("a")}, (), Path("sdk-checkout"))
        return factory.make_surface({Slot("a"): 1, Slot("panel"): 11})


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


def test_touch_points_and_swipes_are_received_without_sdk_types():
    device = DisplayDevice()
    product = surface(device)
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
                event_type="swipe", direction=SimpleNamespace(value="right")
            ),
        )
        assert product.touch.take() == opendeck.TouchPoint(46, 75)
        assert product.touch.take() == opendeck.Swipe(opendeck.Direction.RIGHT)
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


@pytest.mark.parametrize("result", [-1, None, 0x04000201])
def test_image_transport_failure_is_not_reported_as_success(result):
    device = DisplayDevice()
    device.key_result = result
    product = surface(device)
    product.link.open()
    try:
        with pytest.raises(StreamDockError):
            product.images[Slot("a")].draw(b"image")
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

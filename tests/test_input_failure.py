from threading import Thread

import pytest
from test_surface import DisplayDevice, button_surface, surface

from opendeck import InputError, Observer, Slot


class TouchWake(Observer):
    def __init__(self, product):
        self.product = product
        self.calls = []

    def on_change(self):
        def probe():
            acquired = self.product.link._lock.acquire(blocking=False)
            self.calls.append(acquired)
            if acquired:
                self.product.link._lock.release()

        worker = Thread(target=probe, daemon=True)
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive(), "adapter lock probe did not finish"
        assert self.calls[-1], "failure notification held the adapter lock"


@pytest.mark.parametrize("make", [surface, button_surface])
def test_button_queue_overflow_wakes_touch_consumer_and_preserves_failure(make):
    device = DisplayDevice()
    product = make(device)
    product.link.open()
    wake = TouchWake(product)
    product.touch_subject.add(wake)
    try:
        assert product.touch.take() is None
        for _ in range(257):
            device.emit_packet(1, 1)
            device.emit_packet(1, 0)
        assert wake.calls == [True]
        with pytest.raises(InputError):
            product.touch.take()
        take = (
            product.input.take
            if hasattr(product, "input")
            else product.buttons[Slot("a")].take
        )
        with pytest.raises(InputError, match="capacity"):
            take()
        device.emit_packet(1, 1)
        assert wake.calls == [True]
    finally:
        product.touch_subject.remove(wake)
        product.link.close()


@pytest.mark.parametrize("make", [surface, button_surface])
@pytest.mark.parametrize("failure", ["invalid button state", "receiver failed"])
def test_button_failure_wakes_touch_consumer_once(make, failure, monkeypatch):
    device = DisplayDevice()
    product = make(device)
    product.link.open()
    wake = TouchWake(product)
    product.touch_subject.add(wake)
    try:
        if failure == "receiver failed":

            def fail_receive(*_):
                raise OSError(failure)

            monkeypatch.setattr(product.link._receiver, "receive", fail_receive)
            device.emit(1, 1)
        else:
            device.emit(1, 7)
        assert wake.calls == [True]
        with pytest.raises(InputError):
            product.touch.take()
        take = (
            product.input.take
            if hasattr(product, "input")
            else product.buttons[Slot("a")].take
        )
        with pytest.raises(InputError, match=failure):
            take()
        device.emit_packet(1, 1)
        assert wake.calls == [True]
    finally:
        product.touch_subject.remove(wake)
        product.link.close()

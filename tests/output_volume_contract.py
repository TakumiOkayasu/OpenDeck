"""Tests to run against any adapter configured with fully supported fake output."""

from collections.abc import Callable
from threading import Event

import pytest

from opendeck import Observer, OutputVolume


class _Changes(Observer):
    def __init__(self) -> None:
        self.ready = Event()

    def on_change(self) -> None:
        self.ready.set()


class OutputVolumeContract:
    def test_controls_can_be_read_and_changed_independently(self, output: OutputVolume):
        output.set_mute(False)
        output.set_volume(0.25)
        assert output.read_volume() == pytest.approx(0.25)
        assert output.read_mute() is False

        output.set_mute(True)
        assert output.read_mute() is True
        assert output.read_volume() == pytest.approx(0.25)

    @pytest.mark.parametrize("level", [0.0, 1.0])
    def test_volume_accepts_both_endpoints(self, output: OutputVolume, level: float):
        output.set_volume(level)
        assert output.read_volume() == level

    @pytest.mark.parametrize("level", [-0.1, 1.1, float("inf"), float("nan"), True])
    def test_invalid_volume_keeps_previous_value(self, output: OutputVolume, level):
        output.set_volume(0.25)
        with pytest.raises(ValueError):
            output.set_volume(level)
        assert output.read_volume() == pytest.approx(0.25)

    def test_invalid_mute_keeps_previous_value(self, output: OutputVolume):
        output.set_mute(False)
        with pytest.raises(ValueError):
            output.set_mute(1)  # pyright: ignore[reportArgumentType]
        assert output.read_mute() is False

    def test_external_mute_change_notifies_subscriber(
        self, output: OutputVolume, notify_external_mute: Callable[[bool], None]
    ):
        changes = _Changes()
        output.set_mute(False)
        unsubscribe = output.subscribe(changes)
        try:
            notify_external_mute(True)
            assert changes.ready.wait(3.0)
            assert output.read_mute() is True
        finally:
            unsubscribe()
        unsubscribe()

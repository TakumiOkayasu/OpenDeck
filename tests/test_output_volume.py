import pytest

from opendeck import Observer, OutputVolume, VolumeError, VolumeFailure
from opendeck.volume import UnavailableOutputVolume


@pytest.mark.parametrize("reason", [VolumeFailure.DISABLED, VolumeFailure.UNSUPPORTED])
def test_unavailable_output_uses_the_same_contract_and_reports_why(reason):
    output: OutputVolume = UnavailableOutputVolume(reason)
    for operation in (
        output.read_volume,
        output.read_mute,
        lambda: output.set_volume(0.0),
        lambda: output.set_mute(False),
    ):
        with pytest.raises(VolumeError) as caught:
            operation()
        assert caught.value.reason is reason


def test_unavailable_output_subscription_can_be_released_twice():
    class UnexpectedChange(Observer):
        def on_change(self) -> None:
            pytest.fail("An unavailable implementation has no state changes")

    output: OutputVolume = UnavailableOutputVolume(VolumeFailure.DISABLED)
    unsubscribe = output.subscribe(UnexpectedChange())
    unsubscribe()
    unsubscribe()


@pytest.mark.parametrize("level", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_unavailable_output_rejects_invalid_volume(level):
    output: OutputVolume = UnavailableOutputVolume(VolumeFailure.DISABLED)
    with pytest.raises(ValueError):
        output.set_volume(level)


def test_unavailable_output_rejects_non_boolean_mute():
    output: OutputVolume = UnavailableOutputVolume(VolumeFailure.DISABLED)
    with pytest.raises(ValueError):
        output.set_mute(1)  # pyright: ignore[reportArgumentType]

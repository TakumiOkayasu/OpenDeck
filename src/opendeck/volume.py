"""Control of the current default sound output."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from .ports import Observer


class VolumeFailure(StrEnum):
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"
    PERMISSION_DENIED = "permission_denied"
    NO_OUTPUT = "no_output"
    FAILED = "failed"


class VolumeError(RuntimeError):
    def __init__(self, reason: VolumeFailure, detail: str = "") -> None:
        self.reason = reason
        super().__init__(f"{reason}: {detail}" if detail else str(reason))


class OutputVolume(ABC):
    """Read, change, and observe the system's current default output."""

    @abstractmethod
    def read_volume(self) -> float: ...

    @abstractmethod
    def set_volume(self, level: float) -> None: ...

    @abstractmethod
    def read_mute(self) -> bool: ...

    @abstractmethod
    def set_mute(self, muted: bool) -> None: ...

    @abstractmethod
    def subscribe(self, observer: Observer) -> Callable[[], None]: ...


class UnavailableOutputVolume(OutputVolume):
    """An injectable implementation for a disabled or unsupported route."""

    def __init__(
        self, reason: Literal[VolumeFailure.DISABLED, VolumeFailure.UNSUPPORTED]
    ) -> None:
        self._reason = reason

    def read_volume(self) -> float:
        raise VolumeError(self._reason)

    def set_volume(self, level: float) -> None:
        _check_level(level)
        raise VolumeError(self._reason)

    def read_mute(self) -> bool:
        raise VolumeError(self._reason)

    def set_mute(self, muted: bool) -> None:
        _check_mute(muted)
        raise VolumeError(self._reason)

    def subscribe(self, observer: Observer) -> Callable[[], None]:
        return _unsubscribe


def _unsubscribe() -> None:
    pass


def _check_level(level: float) -> None:
    if (
        isinstance(level, bool)
        or not isinstance(level, (int, float))
        or not 0.0 <= level <= 1.0
    ):
        raise ValueError("volume must be a number between 0 and 1")


def _check_mute(muted: bool) -> None:
    if not isinstance(muted, bool):
        raise ValueError("mute must be a boolean")

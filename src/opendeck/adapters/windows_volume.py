"""Windows Core Audio control of the current console output."""

import logging
import sys
from collections.abc import Callable
from threading import Event, Lock, Thread, local
from typing import Protocol, cast

from ..ports import Observer
from ..volume import OutputVolume, VolumeError, VolumeFailure, _check_level, _check_mute


class _Audio(Protocol):
    def _read_output_volume(self) -> tuple[int, float]: ...

    def _read_output_mute(self) -> tuple[int, bool]: ...

    def _set_output_volume(self, level: float) -> int: ...

    def _set_output_mute(self, muted: bool) -> int: ...

    def _WindowsVolumeWatch(self) -> _Watch: ...


class _Watch(Protocol):
    def start(self) -> int: ...

    def wait(self) -> tuple[int, bool]: ...

    def refresh(self) -> int: ...

    def cancel(self) -> None: ...

    def close(self) -> int: ...


_callback = local()


def _check_owner() -> None:
    if getattr(_callback, "active", False):
        raise RuntimeError("Schedule audio unsubscribe on the application owner")


def _native_audio() -> _Audio:
    if sys.platform != "win32":
        raise VolumeError(VolumeFailure.UNSUPPORTED, "Windows is required")
    from .. import _native

    return cast(_Audio, _native)


def _check_status(status: int, operation: str) -> None:
    if not status & 0x80000000:
        return
    reason = {
        0x80070490: VolumeFailure.NO_OUTPUT,
        0x88890004: VolumeFailure.NO_OUTPUT,
        0x80004002: VolumeFailure.UNSUPPORTED,
        0x80070005: VolumeFailure.PERMISSION_DENIED,
    }.get(status, VolumeFailure.FAILED)
    raise VolumeError(reason, f"{operation}: HRESULT 0x{status:08X}")


class WindowsOutputVolume(OutputVolume):
    def __init__(self, api: _Audio | None = None) -> None:
        self._api = _native_audio() if api is None else api
        self._lock = Lock()
        self._subscriptions: list[_Subscription] = []
        self._closed = False

    def read_volume(self) -> float:
        status, level = self._api._read_output_volume()
        _check_status(status, "Read output volume")
        if not 0.0 <= level <= 1.0:
            raise VolumeError(VolumeFailure.FAILED, "Invalid Windows volume value")
        return level

    def set_volume(self, level: float) -> None:
        _check_level(level)
        _check_status(self._api._set_output_volume(level), "Set output volume")

    def read_mute(self) -> bool:
        status, muted = self._api._read_output_mute()
        _check_status(status, "Read output mute")
        return muted

    def set_mute(self, muted: bool) -> None:
        _check_mute(muted)
        _check_status(self._api._set_output_mute(muted), "Set output mute")

    def subscribe(self, observer: Observer) -> Callable[[], None]:
        with self._lock:
            if self._closed:
                raise VolumeError(VolumeFailure.FAILED, "Audio adapter is closed")
            subscription = _Subscription(self._api, observer)
            self._subscriptions.append(subscription)
        try:
            subscription.start()
        except Exception as error:  # codex-rule-ignore: unwind acquired subscription
            try:
                self._unsubscribe(subscription)
            except Exception as cleanup:  # codex-rule-ignore: preserve cleanup failure
                error.add_note(f"Listener cleanup also failed: {cleanup}")
            raise
        return lambda: self._unsubscribe(subscription)

    def _unsubscribe(self, subscription: _Subscription) -> None:
        subscription.close()
        with self._lock:
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)

    def close(self) -> None:
        """Release subscriptions and retry any failed native cleanup."""
        _check_owner()
        with self._lock:
            self._closed = True
            pending = tuple(self._subscriptions)
        errors: list[Exception] = []
        for subscription in pending:
            try:
                self._unsubscribe(subscription)
            except Exception as error:  # codex-rule-ignore: release every subscription
                errors.append(error)
        if errors:
            for error in errors[1:]:
                errors[0].add_note(str(error))
            raise errors[0]


class _Subscription:
    def __init__(self, api: _Audio, observer: Observer) -> None:
        self._api = api
        self._observer = observer
        self._lock = Lock()
        self._ready = Event()
        self._done = Event()
        self._retry = Event()
        self._closed = False
        self._watch: _Watch | None = None
        self._startup_error: Exception | None = None
        self._runtime_error: Exception | None = None
        self._cleanup_error: Exception | None = None
        self._thread = Thread(target=self._run, name="opendeck-audio", daemon=True)

    def start(self) -> None:
        try:
            self._thread.start()
        except RuntimeError:  # codex-rule-ignore: no native resources acquired
            self._done.set()
            raise
        self._ready.wait()
        if self._startup_error is not None:
            raise self._startup_error

    def _run(self) -> None:
        try:
            self._watch = self._api._WindowsVolumeWatch()
            _check_status(self._watch.start(), "Start output notification")
            with self._lock:
                if self._closed:
                    self._watch.cancel()
            self._ready.set()
            self._receive()
        except Exception as error:  # codex-rule-ignore: report worker error to owner
            if self._ready.is_set():
                self._runtime_error = error
                logging.getLogger(__name__).exception(
                    "Windows audio notification failed"
                )
            else:
                self._startup_error = error
        finally:
            self._ready.set()
            self._finish()

    def _receive(self) -> None:
        assert self._watch is not None
        while True:
            status, changed = self._watch.wait()
            _check_status(status, "Wait for output notification")
            with self._lock:
                if self._closed or not changed:
                    return
                status = self._watch.refresh()
                try:
                    _check_status(status, "Refresh output notification")
                    self._runtime_error = None
                except VolumeError as error:  # codex-rule-ignore: preserve rebind error
                    self._runtime_error = error
                    logging.getLogger(__name__).exception("Windows audio rebind failed")
            _callback.active = True
            try:
                self._observer.on_change()
            finally:
                _callback.active = False

    def _finish(self) -> None:
        while True:
            try:
                if self._watch is not None:
                    _check_status(self._watch.close(), "Close output notification")
                self._cleanup_error = None
            except Exception as error:  # codex-rule-ignore: retain native cleanup owner
                self._cleanup_error = error
            self._done.set()
            if self._cleanup_error is None:
                return
            self._retry.wait()
            self._retry.clear()

    def close(self) -> None:
        _check_owner()
        with self._lock:
            self._closed = True
            if self._watch is not None:
                self._watch.cancel()
            if self._done.is_set() and self._cleanup_error is not None:
                self._done.clear()
                self._retry.set()
        self._done.wait()
        if self._cleanup_error is not None:
            raise self._cleanup_error
        if self._runtime_error is not None:
            error, self._runtime_error = self._runtime_error, None
            raise error

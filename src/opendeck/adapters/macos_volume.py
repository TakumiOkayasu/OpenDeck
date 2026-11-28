"""Core Audio control of the current macOS default output device."""

import ctypes
import logging
import sys
from collections.abc import Callable
from itertools import count
from threading import Event, Lock, Thread
from typing import Protocol, cast

from ..ports import Observer
from ..volume import OutputVolume, VolumeError, VolumeFailure, _check_level, _check_mute


class _Audio(Protocol):
    def default_output(self) -> int: ...

    def read_volume(self, device: int) -> float: ...

    def set_volume(self, device: int, level: float) -> None: ...

    def read_mute(self, device: int) -> bool: ...

    def set_mute(self, device: int, muted: bool) -> None: ...

    def watch_default(self, notify: Callable[[], None]) -> Callable[[], None]: ...

    def watch_device(
        self,
        device: int,
        notify: Callable[[], None],
        registrations: list[Callable[[], None]],
    ) -> None: ...


class MacOSOutputVolume(OutputVolume):
    def __init__(self, audio: _Audio | None = None) -> None:
        self._audio = _CoreAudio() if audio is None else audio
        self._owner = Lock()
        self._subscriptions: list[_Subscription] = []
        self._closed = False

    def read_volume(self) -> float:
        return self._audio.read_volume(self._audio.default_output())

    def set_volume(self, level: float) -> None:
        _check_level(level)
        self._audio.set_volume(self._audio.default_output(), level)

    def read_mute(self) -> bool:
        return self._audio.read_mute(self._audio.default_output())

    def set_mute(self, muted: bool) -> None:
        _check_mute(muted)
        self._audio.set_mute(self._audio.default_output(), muted)

    def subscribe(self, observer: Observer) -> Callable[[], None]:
        with self._owner:
            if self._closed:
                raise VolumeError(VolumeFailure.FAILED, "Audio adapter is closed")
            self._retry_failed_starts()
            subscription = _Subscription(self._audio, observer)
            self._subscriptions.append(subscription)
            self._start(subscription)
        return lambda: self._unsubscribe(subscription)

    def _retry_failed_starts(self) -> None:
        for subscription in tuple(self._subscriptions):
            if not subscription.started:
                subscription.close()
                self._subscriptions.remove(subscription)

    def _start(self, subscription: _Subscription) -> None:
        try:
            subscription.start()
        except (VolumeError, RuntimeError) as error:  # codex-rule-ignore: unwind start
            try:
                subscription.close()
            except VolumeError as cleanup:  # codex-rule-ignore: preserve both failures
                error.add_note(f"Listener cleanup also failed: {cleanup}")
            else:
                self._subscriptions.remove(subscription)
            raise

    def _unsubscribe(self, subscription: _Subscription) -> None:
        subscription.close()
        with self._owner:
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)

    def close(self) -> None:
        """Release owned subscriptions, including cleanup from failed starts."""
        with self._owner:
            self._closed = True
            pending = tuple(self._subscriptions)
        _release([lambda sub=sub: self._unsubscribe(sub) for sub in pending])


class _Subscription:
    def __init__(self, audio: _Audio, observer: Observer) -> None:
        self._audio = audio
        self._observer = observer
        self._wake = Event()
        self._lock = Lock()
        self._closed = False
        self._device: int | None = None
        self._device_close: list[Callable[[], None]] = []
        self._default_close: list[Callable[[], None]] = []
        self._error: VolumeError | None = None
        self._observer_error: Exception | None = None
        self._worker: Thread | None = None
        self.started = False

    def start(self) -> None:
        self._default_close.append(self._audio.watch_default(self._wake.set))
        self._rebind()
        self._worker = Thread(target=self._run, name="opendeck-audio", daemon=True)
        self._worker.start()
        self.started = True

    def _rebind(self) -> None:
        try:
            device = self._audio.default_output()
        except VolumeError as error:  # codex-rule-ignore: classify absence
            if error.reason is not VolumeFailure.NO_OUTPUT:
                raise
            device = 0
        if device == self._device:
            return
        self._device = None
        _release(self._device_close)
        if device:
            self._audio.watch_device(device, self._wake.set, self._device_close)
        self._device = device

    def _run(self) -> None:
        while self._wake.wait():
            self._wake.clear()
            with self._lock:
                if self._closed:
                    return
                try:
                    self._rebind()
                    self._error = None
                except VolumeError as error:  # codex-rule-ignore: stores error
                    self._error = error
                    logging.getLogger(__name__).exception(
                        "Core Audio listener rebind failed"
                    )
            try:
                self._observer.on_change()
            except Exception as error:  # codex-rule-ignore: preserve then rethrow bug
                with self._lock:
                    self._observer_error = error
                raise

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._wake.set()
            _release(self._device_close, self._default_close)
            if self._observer_error is not None:
                error, self._observer_error = self._observer_error, None
                if self._error is not None:
                    error.add_note(str(self._error))
                    self._error = None
                raise error
            if self._error is not None:
                error, self._error = self._error, None
                raise error


def _release(*registrations: list[Callable[[], None]]) -> None:
    errors: list[Exception] = []
    for group in registrations:
        for close in tuple(group):
            try:
                close()
            except Exception as error:  # codex-rule-ignore: preserve all cleanup errors
                errors.append(error)
            else:
                group.remove(close)
    if errors:
        for error in errors[1:]:
            errors[0].add_note(str(error))
        raise errors[0]


class _Address(ctypes.Structure):
    _fields_ = [
        ("selector", ctypes.c_uint32),
        ("scope", ctypes.c_uint32),
        ("element", ctypes.c_uint32),
    ]


_ListenerProc = ctypes.CFUNCTYPE(
    ctypes.c_int32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.POINTER(_Address),
    ctypes.c_void_p,
)
_listeners: dict[int, _Listener] = {}
_listener_lock = Lock()
_tokens = count(1)


@_ListenerProc
def _notify(device, count, addresses, token):
    with _listener_lock:
        listener = _listeners.get(token)
        if listener is not None and listener.active:
            listener.notify()
    return 0


class _Listener:
    def __init__(
        self,
        library: ctypes.CDLL,
        device: int,
        address: _Address,
        notify: Callable[[], None],
    ) -> None:
        self.library = library
        self.device = device
        self.address = address
        self.notify = notify
        self.active = True
        self.removed = False
        with _listener_lock:
            self.token = next(_tokens)
            _listeners[self.token] = self
        status = library.AudioObjectAddPropertyListener(
            device, ctypes.byref(address), _notify, self.token
        )
        if status:
            with _listener_lock:
                _listeners.pop(self.token)
            _check_status(status, "AudioObjectAddPropertyListener")

    def close(self) -> None:
        with _listener_lock:
            self.active = False
            if self.removed:
                return
        status = self.library.AudioObjectRemovePropertyListener(
            self.device, ctypes.byref(self.address), _notify, self.token
        )
        _check_status(status, "AudioObjectRemovePropertyListener")
        with _listener_lock:
            self.removed = True
            _listeners.pop(self.token)


def _code(value: str) -> int:
    return int.from_bytes(value.encode("ascii"), "big")


def _address(selector: str, scope: str = "outp") -> _Address:
    return _Address(_code(selector), _code(scope), 0)


def _check_status(status: int, operation: str) -> None:
    if status == 0:
        return
    reason = {
        _code("!hog"): VolumeFailure.PERMISSION_DENIED,
        _code("!obj"): VolumeFailure.NO_OUTPUT,
        _code("!dev"): VolumeFailure.NO_OUTPUT,
        _code("who?"): VolumeFailure.UNSUPPORTED,
        _code("unop"): VolumeFailure.UNSUPPORTED,
    }.get(status, VolumeFailure.FAILED)
    raise VolumeError(reason, f"{operation}: OSStatus {status}")


class _CoreAudio:
    def __init__(self, library: object | None = None) -> None:
        if library is None:
            if sys.platform != "darwin":
                raise VolumeError(VolumeFailure.UNSUPPORTED, "macOS is required")
            library = ctypes.CDLL(
                "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
            )
        self._library = cast(ctypes.CDLL, library)
        self._bind_properties()

    def _bind_properties(self) -> None:
        address = ctypes.POINTER(_Address)
        signatures = {
            "AudioObjectHasProperty": ([ctypes.c_uint32, address], ctypes.c_ubyte),
            "AudioObjectIsPropertySettable": (
                [ctypes.c_uint32, address, ctypes.POINTER(ctypes.c_ubyte)],
                ctypes.c_int32,
            ),
            "AudioObjectGetPropertyData": (
                [
                    ctypes.c_uint32,
                    address,
                    ctypes.c_uint32,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_uint32),
                    ctypes.c_void_p,
                ],
                ctypes.c_int32,
            ),
            "AudioObjectSetPropertyData": (
                [
                    ctypes.c_uint32,
                    address,
                    ctypes.c_uint32,
                    ctypes.c_void_p,
                    ctypes.c_uint32,
                    ctypes.c_void_p,
                ],
                ctypes.c_int32,
            ),
        }
        for name in (
            "AudioObjectAddPropertyListener",
            "AudioObjectRemovePropertyListener",
        ):
            signatures[name] = (
                [ctypes.c_uint32, address, _ListenerProc, ctypes.c_void_p],
                ctypes.c_int32,
            )
        for name, (arguments, result) in signatures.items():
            function = getattr(self._library, name)
            function.argtypes = arguments
            function.restype = result

    def default_output(self) -> int:
        device = ctypes.c_uint32()
        self._read(1, _address("dOut", "glob"), device)
        if device.value == 0:
            raise VolumeError(VolumeFailure.NO_OUTPUT, "No default output device")
        return device.value

    def read_volume(self, device: int) -> float:
        self._require_live(device)
        level = ctypes.c_float()
        self._read(device, _address("volm"), level)
        if not 0.0 <= level.value <= 1.0:
            raise VolumeError(VolumeFailure.FAILED, "Invalid Core Audio volume scalar")
        return level.value

    def set_volume(self, device: int, level: float) -> None:
        self._require_live(device)
        self._write(device, _address("volm"), ctypes.c_float(level))

    def read_mute(self, device: int) -> bool:
        self._require_live(device)
        muted = ctypes.c_uint32()
        self._read(device, _address("mute"), muted)
        return bool(muted.value)

    def set_mute(self, device: int, muted: bool) -> None:
        self._require_live(device)
        self._write(device, _address("mute"), ctypes.c_uint32(muted))

    def _require_live(self, device: int) -> None:
        address = _address("livn", "glob")
        if self._library.AudioObjectHasProperty(device, ctypes.byref(address)):
            alive = ctypes.c_uint32()
            self._read(device, address, alive)
            if not alive.value:
                raise VolumeError(VolumeFailure.NO_OUTPUT, "Output device is not alive")

    def watch_default(self, notify: Callable[[], None]) -> Callable[[], None]:
        return _Listener(self._library, 1, _address("dOut", "glob"), notify).close

    def watch_device(
        self,
        device: int,
        notify: Callable[[], None],
        registrations: list[Callable[[], None]],
    ) -> None:
        for selector, scope in (("volm", "outp"), ("mute", "outp"), ("livn", "glob")):
            address = _address(selector, scope)
            if self._library.AudioObjectHasProperty(device, ctypes.byref(address)):
                registrations.append(
                    _Listener(self._library, device, address, notify).close
                )

    def _require_property(self, device: int, address: _Address) -> None:
        if not self._library.AudioObjectHasProperty(device, ctypes.byref(address)):
            raise VolumeError(VolumeFailure.UNSUPPORTED, "Main output control absent")

    def _read(
        self, device: int, address: _Address, value: ctypes.c_uint32 | ctypes.c_float
    ) -> None:
        self._require_property(device, address)
        size = ctypes.c_uint32(ctypes.sizeof(value))
        status = self._library.AudioObjectGetPropertyData(
            device,
            ctypes.byref(address),
            0,
            None,
            ctypes.byref(size),
            ctypes.byref(value),
        )
        _check_status(status, "AudioObjectGetPropertyData")
        if size.value != ctypes.sizeof(value):
            raise VolumeError(VolumeFailure.FAILED, "Unexpected Core Audio value size")

    def _write(
        self, device: int, address: _Address, value: ctypes.c_uint32 | ctypes.c_float
    ) -> None:
        self._require_property(device, address)
        writable = ctypes.c_ubyte()
        status = self._library.AudioObjectIsPropertySettable(
            device, ctypes.byref(address), ctypes.byref(writable)
        )
        _check_status(status, "AudioObjectIsPropertySettable")
        if not writable.value:
            raise VolumeError(VolumeFailure.UNSUPPORTED, "Main output is read-only")
        status = self._library.AudioObjectSetPropertyData(
            device,
            ctypes.byref(address),
            0,
            None,
            ctypes.sizeof(value),
            ctypes.byref(value),
        )
        _check_status(status, "AudioObjectSetPropertyData")

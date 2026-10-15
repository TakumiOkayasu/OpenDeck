import importlib
import logging
import sys
import threading
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..model import Chord, Slot
from ..ports import Observer, Product
from ..recognition import State, apply, validate_adaptation
from ..source import Source

_LOGGER = logging.getLogger(__name__)
_POLL_INTERVAL = 0.5
_JOIN_TIMEOUT = 2.0
_HEARTBEAT_JOIN_TIMEOUT = 10.1


class _ReaderContext(threading.local):
    def __init__(self) -> None:
        self.packet: tuple[int, bytes] | None = None


class StreamDockError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Sdk:
    manager: Any
    n4pro: type
    button: Any


def _load(sdk_path: Path) -> _Sdk:
    _LOGGER.debug("Loading StreamDock SDK from %s", sdk_path)
    source_path = (sdk_path / "Python-SDK" / "src").resolve()
    if not (source_path / "StreamDock" / "DeviceManager.py").is_file():
        raise StreamDockError(f"SDK source not found: {source_path}")
    loaded = sys.modules.get("StreamDock")
    if loaded is not None:
        loaded_file = getattr(loaded, "__file__", None)
        if loaded_file is None or not Path(loaded_file).resolve().is_relative_to(
            source_path
        ):
            raise StreamDockError("A different StreamDock SDK is already imported")
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))
    try:
        with warnings.catch_warnings():
            # WMI 1.5.1 has invalid docstring escapes. Compilation warnings use
            # the source path rather than the import name.
            warnings.filterwarnings(
                "ignore",
                message=r'"\\_" is an invalid escape sequence\.',
                category=SyntaxWarning,
                module=r"(?:.*[\\/])?wmi$",
            )
            manager_class = importlib.import_module(
                "StreamDock.DeviceManager"
            ).DeviceManager
        manager = manager_class()
        n4pro = importlib.import_module(
            "StreamDock.Devices.StreamDockN4Pro"
        ).StreamDockN4Pro
        button = importlib.import_module("StreamDock.InputTypes").EventType.BUTTON
    except (ImportError, OSError) as error:
        raise StreamDockError(
            f"Cannot load SDK or its native dependencies: {error}"
        ) from error
    return _Sdk(manager, n4pro, button)


def _devices(sdk: _Sdk) -> list[Any]:
    _LOGGER.debug("Enumerating N4 Pro devices")
    return [
        device for device in sdk.manager.enumerate() if isinstance(device, sdk.n4pro)
    ]


def list_devices(sdk_path: Path) -> list[str]:
    return [
        f"{index}: N4 Pro serial={device.get_serial_number()!r}"
        for index, device in enumerate(_devices(_load(sdk_path)))
    ]


class StreamDockFactory:
    def __init__(
        self,
        keys: Mapping[int, Slot],
        chords: tuple[Chord, ...],
        sdk_path: Path,
        device_index: int | None = None,
    ):
        if any(type(key) is not int or not 1 <= key <= 15 for key in keys):
            raise ValueError("N4 Pro keys must be integers from 1 through 15")
        validate_adaptation(keys.values(), chords)
        if device_index is not None and (
            type(device_index) is not int or device_index < 0
        ):
            raise ValueError("Device index must be a nonnegative integer")
        self._keys = dict(keys)
        self._chords = chords
        self._sdk_path = sdk_path
        self._device_index = device_index

    def make(self) -> Product:
        sdk = _load(self._sdk_path)
        devices = _devices(sdk)
        if not devices:
            raise StreamDockError("No N4 Pro device found")
        index = self._device_index
        if index is None:
            if len(devices) != 1:
                raise StreamDockError(
                    "Multiple N4 Pro devices found; specify a device index"
                )
            index = 0
        if index >= len(devices):
            raise StreamDockError(f"N4 Pro device index {index} is out of range")
        device = devices[index]
        _LOGGER.debug(
            "Selected N4 Pro index=%d serial=%r", index, device.get_serial_number()
        )
        source = Source[Slot]()
        link = _Link(device, sdk.button, self._keys, self._chords, source)
        return Product(link, source, source)


class _Link:
    def __init__(
        self,
        device: Any,
        button: Any,
        keys: Mapping[int, Slot],
        chords: tuple[Chord, ...],
        source: Source[Slot],
    ):
        self._device = device
        self._button = button
        self._keys = keys
        self._chords = chords
        self._source = source
        self._state = State()
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._active = False
        self._opened = False
        self._generation = 0
        self._raw_registered = False
        self._reader_context = _ReaderContext()

    def open(self) -> None:
        with self._lifecycle:
            if self._opened:
                raise StreamDockError("Connection is already open")
            with self._lock:
                self._generation += 1
                generation = self._generation
                self._state = State()
            try:
                self._device.set_key_callback(
                    lambda device, event: self._receive(generation, event)
                )
                self._device.set_raw_read_callback(
                    lambda device, data: self._receive_raw(generation, data)
                )
                self._raw_registered = True
                _LOGGER.debug("Opening N4 Pro")
                if not self._device.open():
                    raise StreamDockError("SDK could not open the selected N4 Pro")
                _LOGGER.debug("SDK open completed; initializing N4 Pro")
                self._device.init()
                _LOGGER.debug(
                    "SDK initialization completed; firmware=%r",
                    self._device.firmware_version,
                )
                with self._lock:
                    self._source.start()
                    self._active = True
                    self._opened = True
                self._stop.clear()
                self._monitor = threading.Thread(
                    target=self._watch,
                    args=(generation,),
                    daemon=True,
                    name="streamdock-presence",
                )
                self._monitor.start()
            except Exception as error:
                self._invalidate()
                self._stop.set()
                try:
                    self._close_device()
                except Exception as cleanup_error:
                    raise ExceptionGroup(
                        "SDK startup and cleanup failed", [error, cleanup_error]
                    ) from None
                self._opened = False
                self._monitor = None
                raise

    def _receive_raw(self, generation: int, data: bytes) -> None:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "SDK raw input: length=%d prefix=%s", len(data), data[:32].hex(" ")
            )
        with self._lock:
            if generation == self._generation:
                # The SDK invokes raw and decoded callbacks on the same reader
                # thread. Keep the wire code that its image-key mapping loses.
                self._reader_context.packet = (generation, data)

    def _receive(self, generation: int, event: Any) -> None:
        _LOGGER.debug("SDK decoded input: %r", event)
        notifications: tuple[Observer, ...] = ()
        with self._lock:
            packet = self._reader_context.packet
            if packet is not None and packet[0] == generation:
                self._reader_context.packet = None
            if not self._active or generation != self._generation:
                _LOGGER.debug("Ignoring SDK input before readiness or after close")
                return
            if event.event_type != self._button:
                _LOGGER.debug("Ignoring non-button input: %s", event.event_type)
                return
            key = event.key.value
            if packet is not None and packet[0] == generation:
                data = packet[1]
                if (
                    len(data) >= 11
                    and data[:3] == b"ACK"
                    and data[5:7] == b"OK"
                    and 1 <= data[9] <= 10
                ):
                    # N4 Pro regular-button report IDs differ from image IDs.
                    key = data[9]
                    _LOGGER.debug(
                        "N4 Pro button input: report=%d SDK=%d", key, event.key.value
                    )
            slot = self._keys.get(key)
            if slot is None:
                _LOGGER.debug("Ignoring unmapped button: %s", key)
                return
            if event.state not in (0, 1):
                self._active = False
                self._state = State()
                notifications = self._source.record_failure(
                    StreamDockError("SDK supplied an invalid button state")
                )
            else:
                self._state, slots = apply(
                    self._state, slot, event.state == 1, self._chords
                )
                for recognized in slots:
                    accepted, observers = self._source.enqueue(recognized)
                    notifications += observers
                    if not accepted:
                        self._active = False
                        self._state = State()
                        break
                    _LOGGER.debug("Recognized input: %s", recognized)
        self._source.notify(notifications)

    def _watch(self, generation: int) -> None:
        while not self._stop.wait(_POLL_INTERVAL):
            try:
                present = self._device.transport.enumerate_devices(
                    vendor_id=self._device.vendor_id, product_id=self._device.product_id
                )
                connected = any(
                    device["path"] == self._device.path for device in present
                )
            except Exception as error:
                self._fail(
                    generation,
                    StreamDockError(f"Cannot check device presence: {error}"),
                )
                return
            if not connected:
                self._fail(generation, StreamDockError("N4 Pro disconnected"))
                return

    def _fail(self, generation: int, error: Exception) -> None:
        with self._lock:
            if not self._active or generation != self._generation:
                return
            self._active = False
            self._state = State()
            observers = self._source.record_failure(error)
        self._source.notify(observers)

    def _invalidate(self) -> None:
        with self._lock:
            self._active = False
            self._generation += 1
            self._state = State()
            self._source.close()

    def close(self) -> None:
        _LOGGER.debug("Closing N4 Pro")
        if threading.current_thread() is self._device.read_thread:
            raise StreamDockError(
                "Close the connection from its owner, not the SDK callback thread"
            )
        with self._lifecycle:
            self._invalidate()
            self._stop.set()
            errors: list[Exception] = []
            if (
                self._monitor is not None
                and self._monitor.ident is not None
                and self._monitor is not threading.current_thread()
            ):
                self._monitor.join(_JOIN_TIMEOUT)
                if self._monitor.is_alive():
                    errors.append(
                        StreamDockError("Device presence thread did not stop")
                    )
            if self._opened:
                self._opened = False
                try:
                    self._close_device()
                except Exception as error:
                    errors.append(error)
            if errors:
                raise ExceptionGroup("StreamDock connection cleanup failed", errors)
            _LOGGER.debug("N4 Pro closed")

    def _close_device(self) -> None:
        errors: list[Exception] = []
        try:
            self._device.set_key_callback(None)
        except Exception as error:
            errors.append(error)
        if self._raw_registered:
            try:
                self._device.set_raw_read_callback(None)
                self._raw_registered = False
            except Exception as error:
                errors.append(error)
        try:
            self._device.close(notify=False)
        except Exception as error:
            errors.append(error)
        heartbeat = self._device.heartbeat_thread
        if (
            heartbeat is not None
            and heartbeat.is_alive()
            and heartbeat is not threading.current_thread()
        ):
            try:
                heartbeat.join(_HEARTBEAT_JOIN_TIMEOUT)
            except Exception as error:
                errors.append(error)
        for thread in (self._device.read_thread, self._device.heartbeat_thread):
            if thread is not None and thread.is_alive():
                errors.append(
                    StreamDockError(
                        "SDK worker thread did not stop; native release is unconfirmed"
                    )
                )
        if errors:
            raise ExceptionGroup("SDK device cleanup failed", errors)

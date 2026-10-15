from __future__ import annotations

import threading
import unittest
import warnings
from collections.abc import Callable
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from opendeck.adapters import streamdock
from opendeck.adapters.streamdock import StreamDockError, StreamDockFactory
from opendeck.model import Chord, Slot
from opendeck.source import InputError


class FakeTransport:
    def __init__(self, device: FakeN4Pro) -> None:
        self.device = device
        self.present = True
        self.error: Exception | None = None
        self.polled = threading.Event()

    def enumerate_devices(
        self, vendor_id: int, product_id: int
    ) -> list[dict[str, str]]:
        self.polled.set()
        if self.error is not None:
            raise self.error
        return [{"path": self.device.path}] if self.present else []


class FakeN4Pro:
    def __init__(self, serial: str = "one") -> None:
        self.serial = serial
        self.path = "path-" + serial
        self.vendor_id = 0x5548
        self.product_id = 0x1008
        self.transport = FakeTransport(self)
        self.callback: Callable[[FakeN4Pro, SimpleNamespace], None] | None = None
        self.raw_callback: Callable[[FakeN4Pro, bytes], None] | None = None
        self.firmware_version = "fake-firmware"
        self.opened = 0
        self.initialized = 0
        self.closed: list[bool] = []
        self.open_result = True
        self.init_error: Exception | None = None
        self.close_error: Exception | None = None
        self.init_events: tuple[SimpleNamespace, ...] = ()
        self.read_thread: LiveWorker | None = None
        self.heartbeat_thread: SleepingHeartbeat | None = None

    def get_serial_number(self) -> str:
        return self.serial

    def set_key_callback(
        self, callback: Callable[[FakeN4Pro, SimpleNamespace], None] | None
    ) -> None:
        self.callback = callback

    def set_raw_read_callback(
        self, callback: Callable[[FakeN4Pro, bytes], None] | None
    ) -> None:
        self.raw_callback = callback

    def emit_raw(self, data: bytes) -> None:
        if self.raw_callback is not None:
            self.raw_callback(self, data)

    def open(self) -> bool:
        self.opened += 1
        return self.open_result

    def init(self) -> None:
        self.initialized += 1
        for event in self.init_events:
            callback = self.callback
            assert callback is not None
            callback(self, event)
        if self.init_error is not None:
            raise self.init_error

    def close(self, notify: bool) -> None:
        self.closed.append(notify)
        if self.close_error is not None:
            raise self.close_error

    def read(self) -> None:
        return None

    def emit(self, key: int, state: int, event_type: str = "button") -> None:
        if self.callback is not None:
            self.callback(self, event(key, state, event_type))

    def emit_packet(self, code: int, state: int) -> None:
        self.emit_raw(input_packet(code, state))
        # Reproduce the SDK's image-map-derived IDs, not the intended input IDs.
        sdk_key = {
            1: 11,
            2: 12,
            3: 13,
            4: 14,
            5: 15,
            0x40: 11,
            0x41: 12,
            0x42: 13,
            0x43: 14,
        }.get(code, code)
        self.emit(sdk_key, int(state == 1))


class FakeManager:
    def __init__(self, devices):
        self.devices = devices

    def enumerate(self):
        return self.devices


class Wake:
    def __init__(self):
        self.event = threading.Event()

    def on_change(self):
        self.event.set()


class CallbackObserver:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback

    def on_change(self) -> None:
        self.callback()


class LiveWorker:
    def is_alive(self) -> bool:
        return True


class SleepingHeartbeat:
    def __init__(self) -> None:
        self.alive = True
        self.join_timeouts: list[float] = []

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float) -> None:
        self.join_timeouts.append(timeout)
        self.alive = False


def input_packet(code: int, state: int) -> bytes:
    header = bytes.fromhex("41 43 4b 00 00 4f 4b 00 00")
    return header + bytes((code, state)) + bytes(501)


def event(key: int, state: int, event_type: str = "button") -> SimpleNamespace:
    return SimpleNamespace(
        event_type=event_type, key=SimpleNamespace(value=key), state=state
    )


class SdkLoadingTests(unittest.TestCase):
    def load(self, on_import):
        modules = {
            "StreamDock.DeviceManager": SimpleNamespace(
                DeviceManager=lambda: FakeManager([])
            ),
            "StreamDock.Devices.StreamDockN4Pro": SimpleNamespace(
                StreamDockN4Pro=FakeN4Pro
            ),
            "StreamDock.InputTypes": SimpleNamespace(
                EventType=SimpleNamespace(BUTTON="button")
            ),
        }

        def import_module(name):
            if name == "StreamDock.DeviceManager":
                on_import()
            return modules[name]

        with (
            patch.object(Path, "is_file", return_value=True),
            patch.object(streamdock.sys, "path", []),
            patch.dict(streamdock.sys.modules, {"StreamDock": None}),
            patch.object(
                streamdock.importlib, "import_module", side_effect=import_module
            ),
        ):
            return streamdock._load(Path("sdk-checkout"))

    def test_preimported_sdk_with_unknown_or_foreign_file_is_rejected(self):
        cases = (
            ("none", SimpleNamespace(__file__=None)),
            ("missing", SimpleNamespace()),
            (
                "outside",
                SimpleNamespace(__file__="other-sdk/StreamDock/__init__.py"),
            ),
        )
        for name, loaded in cases:
            with (
                self.subTest(module_file=name),
                patch.object(Path, "is_file", return_value=True),
                patch.object(streamdock.sys, "path", []),
                patch.dict(streamdock.sys.modules, {"StreamDock": loaded}),
                patch.object(streamdock.importlib, "import_module") as import_module,
            ):
                with self.assertRaisesRegex(
                    StreamDockError, "A different StreamDock SDK is already imported"
                ):
                    streamdock._load(Path("sdk-checkout"))
                import_module.assert_not_called()

    def test_wmi_docstring_warnings_are_scoped_to_sdk_import(self):
        source = r'"""GetObjectText\_"""' "\ndef new():\n" r'    """SpawnInstance\_"""'
        for filename in ("wmi.py", "/deps/wmi.py", r"C:\deps\wmi.py"):
            with (
                self.subTest(filename=filename),
                warnings.catch_warnings(record=True) as caught,
            ):
                warnings.simplefilter("always")
                sdk = self.load(partial(compile, source, filename, "exec"))
                self.assertIsInstance(sdk.manager, FakeManager)
                self.assertIs(sdk.n4pro, FakeN4Pro)
                self.assertEqual(sdk.button, "button")
                self.assertEqual(caught, [])
                compile(source, filename, "exec")
                self.assertEqual(len(caught), 2)

    def test_unrelated_import_warnings_remain_visible(self):
        cases = (
            (r'"""GetObjectText\_"""', "other.py"),
            (r'"""Other escape\q"""', "wmi.py"),
        )
        for source, filename in cases:
            with (
                self.subTest(source=source, filename=filename),
                warnings.catch_warnings(record=True) as caught,
            ):
                warnings.simplefilter("always")
                self.load(partial(compile, source, filename, "exec"))
                self.assertEqual(len(caught), 1)
                self.assertIs(caught[0].category, SyntaxWarning)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.load(
                lambda: warnings.warn_explicit(
                    r'"\_" is an invalid escape sequence.', UserWarning, "wmi.py", 1
                )
            )
            self.assertEqual(len(caught), 1)
            self.assertIs(caught[0].category, UserWarning)

    def test_failed_import_restores_warning_filters(self):
        def fail():
            raise ImportError("missing dependency")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with self.assertRaisesRegex(StreamDockError, "missing dependency"):
                self.load(fail)
            compile(r'"""GetObjectText\_"""', "wmi.py", "exec")
            self.assertEqual(len(caught), 1)


class StreamDockTests(unittest.TestCase):
    def make(self, devices=None, *, index=None, chords=(), keys=None):
        devices = [FakeN4Pro()] if devices is None else devices
        sdk = streamdock._Sdk(FakeManager(devices), FakeN4Pro, "button")
        with patch.object(streamdock, "_load", return_value=sdk):
            return StreamDockFactory(
                {1: Slot("primary"), 2: Slot("secondary")} if keys is None else keys,
                chords,
                Path("sdk-checkout"),
                device_index=index,
            ).make()

    def test_make_is_unopened_and_native_import_is_lazy(self):
        device = FakeN4Pro()
        product = self.make([device])
        self.assertEqual(device.opened, 0)
        self.assertIsNone(product.input.take())
        self.assertIs(product.input, product.subject)
        product.link.close()
        self.assertEqual(device.closed, [])

    def test_only_n4pro_is_selected_and_multiple_require_explicit_index(self):
        one, two = FakeN4Pro("one"), FakeN4Pro("two")
        with self.assertRaisesRegex(StreamDockError, "Multiple"):
            self.make([one, two])
        product = self.make([object(), one, two], index=1)
        product.link.open()
        product.link.close()
        self.assertEqual(one.opened, 0)
        self.assertEqual(two.opened, 1)
        with self.assertRaisesRegex(StreamDockError, "out of range"):
            self.make([one], index=1)
        with self.assertRaisesRegex(StreamDockError, "No N4 Pro"):
            self.make([object()])

    def test_unavailable_chord_is_rejected_before_loading_the_sdk(self):
        chord = Chord(
            frozenset({Slot("primary"), Slot("unavailable")}), Slot("combined")
        )
        with (
            patch.object(streamdock, "_load") as load,
            self.assertRaisesRegex(ValueError, "adapted base slots"),
        ):
            StreamDockFactory({1: Slot("primary")}, (chord,), Path("sdk-checkout"))
        load.assert_not_called()

    def test_list_uses_the_same_filtered_indices(self):
        sdk = streamdock._Sdk(
            FakeManager([object(), FakeN4Pro("two")]), FakeN4Pro, "button"
        )
        with patch.object(streamdock, "_load", return_value=sdk):
            self.assertEqual(
                streamdock.list_devices(Path("sdk-checkout")),
                ["0: N4 Pro serial='two'"],
            )

    def test_button_events_become_ideal_slots_and_other_inputs_are_ignored(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        self.addCleanup(product.link.close)
        for key, kind in ((1, "knob"), (15, "button")):
            device.emit(key, 1, kind)
            device.emit(key, 0, kind)
        device.emit(1, 1)
        device.emit(1, 1)
        device.emit(1, 0)
        self.assertEqual(product.input.take(), Slot("primary"))
        self.assertIsNone(product.input.take())

    def test_packet_button_numbers_are_independent_of_sdk_image_mapping(self):
        for code in range(1, 11):
            with self.subTest(code=code):
                device = FakeN4Pro()
                slot = Slot("pressed")
                product = self.make([device], keys={code: slot})
                product.link.open()
                try:
                    device.emit_packet(code, 1)
                    self.assertIsNone(product.input.take())
                    device.emit_packet(code, 0)
                    self.assertEqual(product.input.take(), slot)
                    self.assertIsNone(product.input.take())
                finally:
                    product.link.close()

    def test_reported_primary_and_secondary_form_one_chord(self):
        device = FakeN4Pro()
        chord = Chord(frozenset({Slot("primary"), Slot("secondary")}), Slot("together"))
        product = self.make([device], chords=(chord,))
        product.link.open()
        self.addCleanup(product.link.close)
        for code, state in ((1, 1), (2, 1), (2, 0), (1, 0)):
            device.emit_packet(code, state)
        self.assertEqual(product.input.take(), Slot("together"))
        self.assertIsNone(product.input.take())

    def test_touch_release_does_not_release_a_regular_button(self):
        device = FakeN4Pro()
        product = self.make([device], keys={1: Slot("primary"), 11: Slot("touch")})
        product.link.open()
        self.addCleanup(product.link.close)
        device.emit_packet(1, 1)
        device.emit_packet(0x40, 0)
        self.assertIsNone(product.input.take())
        device.emit_packet(1, 0)
        self.assertEqual(product.input.take(), Slot("primary"))
        self.assertIsNone(product.input.take())
        device.emit_packet(0x40, 1)
        device.emit_packet(0x40, 0)
        self.assertEqual(product.input.take(), Slot("touch"))
        self.assertIsNone(product.input.take())

    def test_packet_context_is_consumed_by_its_decoded_event(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        self.addCleanup(product.link.close)
        device.emit_packet(1, 1)
        device.emit(2, 1)
        device.emit(2, 0)
        self.assertEqual(product.input.take(), Slot("secondary"))
        device.emit_packet(1, 0)
        self.assertEqual(product.input.take(), Slot("primary"))
        self.assertIsNone(product.input.take())

    def test_packet_context_is_local_to_the_sdk_reader_thread(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        self.addCleanup(product.link.close)
        device.emit_raw(input_packet(1, 1))

        def other_reader() -> None:
            device.emit(2, 1)
            device.emit(2, 0)

        worker = threading.Thread(target=other_reader)
        worker.start()
        worker.join(1.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(product.input.take(), Slot("secondary"))
        device.emit(11, 1)
        device.emit_packet(1, 0)
        self.assertEqual(product.input.take(), Slot("primary"))
        self.assertIsNone(product.input.take())

    def test_stale_callbacks_cannot_replace_a_reopened_packet_context(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        old_raw, old_key = device.raw_callback, device.callback
        assert old_raw is not None
        assert old_key is not None
        product.link.close()
        product.link.open()
        self.addCleanup(product.link.close)
        device.emit_raw(input_packet(1, 1))
        old_raw(device, input_packet(2, 1))
        old_key(device, event(12, 1))
        device.emit(11, 1)
        device.emit_packet(1, 0)
        self.assertEqual(product.input.take(), Slot("primary"))
        self.assertIsNone(product.input.take())

    def test_debug_logging_observes_raw_and_ignored_inputs_without_dispatch(self):
        device = FakeN4Pro()
        device.init_events = (event(1, 1), event(1, 0))
        with self.assertLogs(streamdock._LOGGER, level="DEBUG") as captured:
            product = self.make([device])
            product.link.open()
            try:
                self.assertIsNotNone(device.raw_callback)
                device.emit_raw(bytes.fromhex("00 aa 41 43 4b"))
                device.emit(15, 1)
                device.emit(15, 0)
                device.emit(1, 1, "knob")
                self.assertIsNone(product.input.take())
                device.emit(1, 1)
                device.emit(1, 0)
                self.assertEqual(product.input.take(), Slot("primary"))
            finally:
                product.link.close()
        output = "\n".join(captured.output)
        self.assertIn("Selected N4 Pro index=0 serial='one'", output)
        self.assertIn("Opening N4 Pro", output)
        self.assertIn("SDK open completed; initializing N4 Pro", output)
        self.assertIn("SDK initialization completed; firmware='fake-firmware'", output)
        self.assertIn("SDK raw input: length=5 prefix=00 aa 41 43 4b", output)
        self.assertIn("SDK decoded input:", output)
        self.assertIn("Ignoring SDK input before readiness or after close", output)
        self.assertIn("Ignoring unmapped button: 15", output)
        self.assertIn("Ignoring non-button input: knob", output)
        self.assertIn("Recognized input: primary", output)
        self.assertIn("N4 Pro closed", output)
        self.assertIsNone(device.raw_callback)
        self.assertIsNone(device.callback)

    def test_raw_input_is_adapted_without_enabling_debug_logging(self):
        device = FakeN4Pro()
        with self.assertNoLogs(streamdock._LOGGER, level="WARNING"):
            product = self.make([device])
            product.link.open()
            try:
                self.assertIsNotNone(device.raw_callback)
                device.emit_packet(1, 1)
                device.emit_packet(1, 0)
                self.assertEqual(product.input.take(), Slot("primary"))
                self.assertIsNone(product.input.take())
            finally:
                product.link.close()
        self.assertIsNone(device.raw_callback)

    def test_startup_failure_clears_the_debug_raw_callback(self):
        device = FakeN4Pro()
        device.init_error = RuntimeError("init failed")
        with self.assertLogs(streamdock._LOGGER, level="DEBUG"):
            product = self.make([device])
            with self.assertRaisesRegex(RuntimeError, "init failed"):
                product.link.open()
        self.assertIsNone(device.raw_callback)
        self.assertIsNone(device.callback)
        self.assertEqual(device.closed, [False])

    def test_overflow_invalidates_recognition_and_late_callbacks_are_ignored(self):
        device = FakeN4Pro()
        product = self.make([device])
        link = cast(streamdock._Link, product.link)
        product.link.open()
        self.addCleanup(product.link.close)
        for _ in range(257):
            device.emit(1, 1)
            device.emit(1, 0)
        with self.assertRaisesRegex(InputError, "capacity"):
            product.input.take()
        self.assertFalse(link._active)
        self.assertFalse(link._state.held)
        device.emit(2, 1)
        self.assertFalse(link._state.held)

    def test_input_and_fault_notifications_run_outside_the_adapter_lock(self):
        device = FakeN4Pro()
        product = self.make([device])
        link = cast(streamdock._Link, product.link)
        observed: list[bool] = []

        def check() -> None:
            acquired = link._lock.acquire(blocking=False)
            observed.append(acquired)
            if acquired:
                link._lock.release()

        def on_change() -> None:
            worker = threading.Thread(target=check)
            worker.start()
            worker.join(1.0)
            self.assertFalse(worker.is_alive())

        product.subject.add(CallbackObserver(on_change))
        product.link.open()
        self.addCleanup(product.link.close)
        device.emit(1, 1)
        device.emit(1, 0)
        self.assertEqual(observed, [True])
        device.emit(1, 9)
        self.assertEqual(observed, [True, True])
        with self.assertRaisesRegex(InputError, "invalid button state"):
            product.input.take()

    def test_chord_emits_one_ideal_slot_without_member_singles(self):
        device = FakeN4Pro()
        chord = Chord(frozenset({Slot("primary"), Slot("secondary")}), Slot("combined"))
        product = self.make([device], chords=(chord,))
        product.link.open()
        self.addCleanup(product.link.close)
        device.emit(1, 1)
        device.emit(2, 1)
        device.emit(1, 0)
        device.emit(2, 0)
        self.assertEqual(product.input.take(), Slot("combined"))
        self.assertIsNone(product.input.take())

    def test_init_inputs_are_not_accepted(self):
        device = FakeN4Pro()
        device.init_events = (event(1, 1), event(1, 0))
        product = self.make([device])
        product.link.open()
        self.addCleanup(product.link.close)
        self.assertIsNone(product.input.take())
        device.emit(1, 1)
        device.emit(1, 0)
        self.assertEqual(product.input.take(), Slot("primary"))

    def test_false_open_is_failure_and_partial_connection_is_cleaned(self):
        device = FakeN4Pro()
        device.open_result = False
        product = self.make([device])
        with self.assertRaisesRegex(StreamDockError, "could not open"):
            product.link.open()
        self.assertEqual(device.initialized, 0)
        self.assertEqual(device.closed, [False])
        self.assertIsNone(device.callback)
        self.assertIsNone(product.input.take())

    def test_init_error_is_preserved_and_partial_connection_is_cleaned(self):
        device = FakeN4Pro()
        device.init_error = RuntimeError("init failed")
        product = self.make([device])
        with self.assertRaisesRegex(RuntimeError, "init failed"):
            product.link.open()
        self.assertEqual(device.closed, [False])
        self.assertIsNone(device.callback)

    def test_startup_and_cleanup_failures_are_both_reported(self):
        device = FakeN4Pro()
        device.init_error = RuntimeError("init failed")
        device.close_error = RuntimeError("close failed")
        product = self.make([device])
        with self.assertRaises(ExceptionGroup) as caught:
            product.link.open()
        self.assertIs(caught.exception.exceptions[0], device.init_error)
        cleanup_error = caught.exception.exceptions[1]
        assert isinstance(cleanup_error, ExceptionGroup)
        self.assertIs(cleanup_error.exceptions[0], device.close_error)

    def test_monitor_start_failure_cleans_the_opened_sdk_device(self):
        device = FakeN4Pro()
        product = self.make([device])
        with (
            patch.object(
                threading.Thread, "start", side_effect=RuntimeError("thread failed")
            ),
            self.assertRaisesRegex(RuntimeError, "thread failed"),
        ):
            product.link.open()
        self.assertEqual(device.closed, [False])
        self.assertIsNone(product.input.take())
        self.assertIsNone(device.callback)
        product.link.close()

    def test_disconnect_clears_pending_requests_and_reports_input_failure(self):
        device = FakeN4Pro()
        product = self.make([device])
        wake = Wake()
        product.subject.add(wake)
        with patch.object(streamdock, "_POLL_INTERVAL", 0.01):
            product.link.open()
            self.addCleanup(product.link.close)
            device.emit(1, 1)
            device.emit(1, 0)
            wake.event.clear()
            device.transport.present = False
            self.assertTrue(wake.event.wait(1.0))
            with self.assertRaisesRegex(InputError, "disconnected"):
                product.input.take()

    def test_none_read_does_not_mean_disconnect_and_monitor_stops_on_close(self):
        device = FakeN4Pro()
        product = self.make([device])
        with patch.object(streamdock, "_POLL_INTERVAL", 0.01):
            product.link.open()
            self.assertIsNone(device.read())
            self.assertTrue(device.transport.polled.wait(1.0))
            self.assertIsNone(product.input.take())
            product.link.close()
        monitor = cast(streamdock._Link, product.link)._monitor
        assert monitor is not None
        self.assertFalse(monitor.is_alive())
        self.assertEqual(device.closed, [False])

    def test_presence_check_error_is_not_reinterpreted_as_no_input(self):
        device = FakeN4Pro()
        device.transport.error = RuntimeError("enumeration failed")
        product = self.make([device])
        wake = Wake()
        product.subject.add(wake)
        with patch.object(streamdock, "_POLL_INTERVAL", 0.01):
            product.link.open()
            self.addCleanup(product.link.close)
            self.assertTrue(wake.event.wait(1.0))
            with self.assertRaisesRegex(InputError, "enumeration failed"):
                product.input.take()

    def test_close_discards_unhanded_requests_but_not_a_taken_slot(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        device.emit(1, 1)
        device.emit(1, 0)
        handed = product.input.take()
        device.emit(2, 1)
        device.emit(2, 0)
        callback = device.callback
        assert callback is not None
        product.link.close()
        callback(device, event(1, 1))
        callback(device, event(1, 0))
        self.assertEqual(handed, Slot("primary"))
        self.assertIsNone(product.input.take())

    def test_previous_callback_is_invalid_even_after_reopening(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        callback = device.callback
        assert callback is not None
        product.link.close()
        product.link.open()
        self.addCleanup(product.link.close)
        callback(device, event(1, 1))
        callback(device, event(1, 0))
        self.assertIsNone(product.input.take())
        device.emit(2, 1)
        device.emit(2, 0)
        self.assertEqual(product.input.take(), Slot("secondary"))

    def test_live_sdk_worker_is_reported_as_unconfirmed_cleanup(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        device.read_thread = LiveWorker()
        with self.assertRaises(ExceptionGroup) as caught:
            product.link.close()
        cleanup_error = caught.exception.exceptions[0]
        assert isinstance(cleanup_error, ExceptionGroup)
        self.assertIn(
            "native release is unconfirmed",
            str(cleanup_error.exceptions[0]),
        )
        self.assertIsNone(device.callback)

    def test_sleeping_heartbeat_can_finish_after_sdk_close_timeout(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        heartbeat = SleepingHeartbeat()
        device.heartbeat_thread = heartbeat
        product.link.close()
        self.assertEqual(heartbeat.join_timeouts, [10.1])
        self.assertFalse(heartbeat.is_alive())
        self.assertEqual(device.closed, [False])

    def test_close_error_is_not_silently_ignored(self):
        device = FakeN4Pro()
        product = self.make([device])
        product.link.open()
        device.close_error = RuntimeError("close failed")
        with self.assertRaises(ExceptionGroup) as caught:
            product.link.close()
        cleanup_error = caught.exception.exceptions[0]
        assert isinstance(cleanup_error, ExceptionGroup)
        self.assertIs(cleanup_error.exceptions[0], device.close_error)
        monitor = cast(streamdock._Link, product.link)._monitor
        assert monitor is not None
        self.assertFalse(monitor.is_alive())


if __name__ == "__main__":
    unittest.main()

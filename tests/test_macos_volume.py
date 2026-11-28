import ctypes
from threading import Barrier, Event

import pytest
from output_volume_contract import OutputVolumeContract

from opendeck.adapters.macos_volume import MacOSOutputVolume, _CoreAudio
from opendeck.volume import VolumeError, VolumeFailure


class FakeAudio:
    def __init__(self):
        self.device = 10
        self.values = {10: [0.25, False], 20: [0.8, True]}
        self.calls = []
        self.listeners = {}
        self.closed = []
        self.watch_failure = False
        self.close_failures = set()

    def default_output(self):
        self.calls.append(("default",))
        if self.device == 0:
            raise VolumeError(VolumeFailure.NO_OUTPUT)
        return self.device

    def read_volume(self, device):
        return self.values[device][0]

    def set_volume(self, device, level):
        self.values[device][0] = level

    def read_mute(self, device):
        return self.values[device][1]

    def set_mute(self, device, muted):
        self.values[device][1] = muted

    def watch_default(self, notify):
        return self.watch(1, notify)

    def watch_device(self, device, notify, registrations):
        if self.watch_failure:
            raise VolumeError(VolumeFailure.FAILED, "registration failed")
        registrations.append(self.watch(device, notify))

    def watch(self, device, notify):
        self.listeners[device] = notify

        def close():
            if device in self.close_failures:
                raise VolumeError(VolumeFailure.FAILED, "removal failed")
            self.closed.append(device)
            self.listeners.pop(device, None)

        return close


class Wake:
    def __init__(self):
        self.event = Event()

    def on_change(self):
        self.event.set()


class TestMacOutputVolumeContract(OutputVolumeContract):
    @pytest.fixture
    def audio(self):
        return FakeAudio()

    @pytest.fixture
    def output(self, audio):
        return MacOSOutputVolume(audio)

    @pytest.fixture
    def notify_external_mute(self, audio):
        def notify(muted):
            audio.values[audio.device][1] = muted
            audio.listeners[audio.device]()

        return notify


def test_default_output_is_resolved_for_each_read_and_write():
    audio = FakeAudio()
    output = MacOSOutputVolume(audio)
    assert output.read_volume() == 0.25
    assert output.read_mute() is False
    audio.device = 20
    output.set_volume(0.6)
    output.set_mute(False)
    assert output.read_volume() == 0.6
    assert output.read_mute() is False
    assert audio.values[10] == [0.25, False]
    assert len(audio.calls) == 6


@pytest.mark.parametrize("level", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_invalid_volume_does_not_call_the_os(level):
    audio = FakeAudio()
    with pytest.raises(ValueError):
        MacOSOutputVolume(audio).set_volume(level)
    assert audio.calls == []


def test_missing_output_is_an_error():
    audio = FakeAudio()
    audio.device = 0
    with pytest.raises(VolumeError) as caught:
        MacOSOutputVolume(audio).read_volume()
    assert caught.value.reason is VolumeFailure.NO_OUTPUT


class Function:
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *args):
        return self.implementation(*args)


class FakeLibrary:
    def __init__(self):
        self.values = {"dOut": 10, "volm": 0.25, "mute": 0, "livn": 1}
        self.status = 0
        self.has_property = True
        self.writable = True
        self.calls = []
        self.registrations = {}
        self.add_failures = {}
        self.remove_failures = {}
        self.AudioObjectHasProperty = Function(lambda *args: self.has_property)
        self.AudioObjectIsPropertySettable = Function(self.is_settable)
        self.AudioObjectGetPropertyData = Function(self.read)
        self.AudioObjectSetPropertyData = Function(self.write)
        self.AudioObjectAddPropertyListener = Function(self.add)
        self.AudioObjectRemovePropertyListener = Function(self.remove)

    def selector(self, address):
        return (
            ctypes.cast(address, ctypes.POINTER(ctypes.c_uint32))[0]
            .to_bytes(4, "big")
            .decode("ascii")
        )

    def is_settable(self, device, address, writable):
        ctypes.cast(writable, ctypes.POINTER(ctypes.c_ubyte))[0] = self.writable
        return self.status

    def read(self, device, address, qualifier_size, qualifier, size, value):
        selector = self.selector(address)
        scalar = ctypes.c_float if selector == "volm" else ctypes.c_uint32
        ctypes.cast(value, ctypes.POINTER(scalar))[0] = self.values[selector]
        self.calls.append(("read", device, selector))
        return self.status

    def write(self, device, address, qualifier_size, qualifier, size, value):
        selector = self.selector(address)
        scalar = ctypes.c_float if selector == "volm" else ctypes.c_uint32
        self.values[selector] = ctypes.cast(value, ctypes.POINTER(scalar))[0]
        self.calls.append(("write", device, selector))
        return self.status

    def add(self, device, address, callback, token):
        key = (device, self.selector(address))
        status = self.add_failures.get(key, 0)
        if status == 0:
            self.registrations[key] = (callback, token)
        return status

    def remove(self, device, address, callback, token):
        key = (device, self.selector(address))
        status = self.remove_failures.get(key, 0)
        if status == 0:
            self.registrations.pop(key)
        return status


def test_native_boundary_uses_typed_default_volume_and_mute_properties():
    library = FakeLibrary()
    audio = _CoreAudio(library)
    assert audio.default_output() == 10
    assert audio.read_volume(10) == 0.25
    assert audio.read_mute(10) is False
    audio.set_volume(10, 0.75)
    audio.set_mute(10, True)
    assert audio.read_volume(10) == 0.75
    assert audio.read_mute(10) is True


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("!hog", "permission_denied"),
        ("!dev", "no_output"),
        ("who?", "unsupported"),
        ("nope", "failed"),
    ],
)
def test_native_failures_preserve_the_os_status(status, reason):
    library = FakeLibrary()
    library.status = int.from_bytes(status.encode("ascii"), "big")
    with pytest.raises(VolumeError) as caught:
        _CoreAudio(library).read_volume(10)
    assert caught.value.reason == reason
    assert str(library.status) in str(caught.value)


def test_absent_or_read_only_main_control_is_unsupported():
    library = FakeLibrary()
    audio = _CoreAudio(library)
    library.has_property = False
    with pytest.raises(VolumeError, match="unsupported"):
        audio.read_volume(10)
    library.has_property = True
    library.writable = False
    with pytest.raises(VolumeError, match="unsupported"):
        audio.set_mute(10, True)
    assert library.calls == [("read", 10, "livn")]


def test_external_notifications_switch_device_and_release_all_registrations():
    audio = FakeAudio()
    output = MacOSOutputVolume(audio)
    wake = Wake()
    close = output.subscribe(wake)
    try:
        audio.listeners[10]()
        assert wake.event.wait(1)
        wake.event.clear()
        audio.device = 20
        audio.listeners[1]()
        assert wake.event.wait(1)
        assert output.read_volume() == 0.8
        assert 10 not in audio.listeners
        assert set(audio.listeners) == {1, 20}
    finally:
        close()
    close()
    assert audio.listeners == {}
    assert sorted(audio.closed) == [1, 10, 20]


def test_subscription_survives_no_output_and_reacquires_later():
    audio = FakeAudio()
    audio.device = 0
    wake = Wake()
    close = MacOSOutputVolume(audio).subscribe(wake)
    try:
        assert set(audio.listeners) == {1}
        audio.device = 20
        audio.listeners[1]()
        assert wake.event.wait(1)
        assert set(audio.listeners) == {1, 20}
    finally:
        close()


def test_native_listener_ignores_late_callback_and_keeps_callback_alive_on_failure():
    library = FakeLibrary()
    event = Event()
    close = _CoreAudio(library).watch_default(event.set)
    callback, token = library.registrations[(1, "dOut")]
    assert callback(1, 0, None, token) == 0
    assert event.is_set()
    event.clear()
    library.remove_failures[(1, "dOut")] = 1
    with pytest.raises(VolumeError, match="OSStatus 1"):
        close()
    assert callback(1, 0, None, token) == 0
    assert not event.is_set()
    library.remove_failures.clear()
    close()
    close()
    assert callback(1, 0, None, token) == 0
    assert not event.is_set()
    assert library.registrations == {}


def test_native_partial_registration_failure_releases_previous_registrations():
    library = FakeLibrary()
    library.add_failures[(10, "mute")] = 1
    with pytest.raises(VolumeError, match="OSStatus 1"):
        MacOSOutputVolume(_CoreAudio(library)).subscribe(Wake())
    assert library.registrations == {}


def test_initial_subscription_failure_unwinds_default_registration():
    audio = FakeAudio()
    audio.watch_failure = True
    with pytest.raises(VolumeError, match="registration failed"):
        MacOSOutputVolume(audio).subscribe(Wake())
    assert audio.listeners == {}
    assert audio.closed == [1]


def test_async_rebind_failure_is_reported_on_release_and_does_not_poison_reads(caplog):
    audio = FakeAudio()
    wake = Wake()
    output = MacOSOutputVolume(audio)
    close = output.subscribe(wake)
    audio.watch_failure = True
    audio.device = 20
    audio.listeners[1]()
    assert wake.event.wait(1)
    assert output.read_volume() == 0.8
    assert "Core Audio listener rebind failed" in caplog.text
    with pytest.raises(VolumeError, match="registration failed"):
        close()
    close()
    assert audio.listeners == {}


def test_cleanup_failure_is_retryable_and_other_listeners_are_released():
    audio = FakeAudio()
    close = MacOSOutputVolume(audio).subscribe(Wake())
    audio.close_failures.add(10)
    with pytest.raises(VolumeError, match="removal failed"):
        close()
    assert set(audio.listeners) == {10}
    audio.close_failures.clear()
    close()
    assert audio.listeners == {}


def test_rebind_can_recover_after_failed_removal_even_if_old_output_returns():
    audio = FakeAudio()
    wake = Wake()
    close = MacOSOutputVolume(audio).subscribe(wake)
    try:
        audio.close_failures.add(10)
        audio.device = 20
        audio.listeners[1]()
        assert wake.event.wait(1)
        wake.event.clear()
        audio.close_failures.clear()
        audio.device = 10
        audio.listeners[1]()
        assert wake.event.wait(1)
        assert audio.closed == [10]
    finally:
        close()


def test_selected_but_dead_device_rejects_control_reads_and_writes():
    library = FakeLibrary()
    library.values["livn"] = 0
    audio = _CoreAudio(library)
    for operation in (
        lambda: audio.read_volume(10),
        lambda: audio.read_mute(10),
        lambda: audio.set_volume(10, 0.75),
        lambda: audio.set_mute(10, True),
    ):
        with pytest.raises(VolumeError, match="no_output"):
            operation()
    assert all(call[2] == "livn" for call in library.calls)


def test_failed_start_retains_cleanup_owner_until_adapter_close_retries():
    audio = FakeAudio()
    audio.watch_failure = True
    audio.close_failures.add(1)
    output = MacOSOutputVolume(audio)
    with pytest.raises(VolumeError, match="registration failed") as caught:
        output.subscribe(Wake())
    assert any("removal failed" in note for note in caught.value.__notes__)
    audio.close_failures.clear()
    output.close()
    assert audio.listeners == {}


def test_worker_start_failure_releases_all_registered_listeners(monkeypatch):
    def fail_start(worker):
        raise RuntimeError("cannot start worker")

    monkeypatch.setattr("opendeck.adapters.macos_volume.Thread.start", fail_start)
    audio = FakeAudio()
    with pytest.raises(RuntimeError, match="cannot start worker"):
        MacOSOutputVolume(audio).subscribe(Wake())
    assert audio.listeners == {}


def test_partial_native_start_and_failed_cleanup_remain_owned():
    library = FakeLibrary()
    library.add_failures[(10, "mute")] = 1
    library.remove_failures[(10, "volm")] = 2
    output = MacOSOutputVolume(_CoreAudio(library))
    with pytest.raises(VolumeError, match="OSStatus 1") as caught:
        output.subscribe(Wake())
    assert any("OSStatus 2" in note for note in caught.value.__notes__)
    assert set(library.registrations) == {(10, "volm")}
    library.remove_failures.clear()
    output.close()
    assert library.registrations == {}


def test_dead_selected_device_stays_watched_for_recovery_on_the_same_id():
    library = FakeLibrary()
    output = MacOSOutputVolume(_CoreAudio(library))
    wake = Wake()
    close = output.subscribe(wake)
    try:
        callback, token = library.registrations[(10, "livn")]
        library.values["livn"] = 0
        callback(10, 0, None, token)
        assert wake.event.wait(1)
        with pytest.raises(VolumeError, match="no_output"):
            output.read_mute()
        wake.event.clear()
        library.values["livn"] = 1
        callback(10, 0, None, token)
        assert wake.event.wait(1)
        assert output.read_volume() == 0.25
    finally:
        close()


@pytest.mark.parametrize("level", [-0.1, 1.1, float("inf"), float("nan")])
def test_invalid_native_volume_is_an_explicit_failure(level):
    library = FakeLibrary()
    library.values["volm"] = level
    with pytest.raises(VolumeError, match="failed"):
        _CoreAudio(library).read_volume(10)


def test_observer_bug_is_reported_by_thread_and_rethrown_after_cleanup(monkeypatch):
    reported = Event()
    failures = []

    def record_failure(arguments):
        failures.append(arguments.exc_value)
        reported.set()

    class BrokenObserver:
        def on_change(self):
            raise ValueError("extension bug")

    monkeypatch.setattr("threading.excepthook", record_failure)
    audio = FakeAudio()
    close = MacOSOutputVolume(audio).subscribe(BrokenObserver())
    audio.listeners[10]()
    assert reported.wait(1)
    with pytest.raises(ValueError, match="extension bug") as caught:
        close()
    assert caught.value is failures[0]
    assert audio.listeners == {}
    close()


def test_adapter_close_releases_other_subscriptions_after_observer_bug(monkeypatch):
    reported = Event()

    class BrokenObserver:
        def on_change(self):
            raise ValueError("extension bug")

    monkeypatch.setattr("threading.excepthook", lambda arguments: reported.set())
    audio = FakeAudio()
    output = MacOSOutputVolume(audio)
    output.subscribe(BrokenObserver())
    audio.listeners[10]()
    assert reported.wait(1)
    audio.device = 20
    output.subscribe(Wake())
    with pytest.raises(ValueError, match="extension bug"):
        output.close()
    assert audio.listeners == {}
    assert 10 in audio.closed
    assert 20 in audio.closed
    output.close()


def test_concurrent_observers_can_close_the_adapter_without_waiting_on_each_other():
    audio = FakeAudio()
    output = MacOSOutputVolume(audio)
    ready = Barrier(2)
    finished = []
    done = Event()

    class CloseTogether:
        def on_change(self):
            ready.wait(timeout=1)
            output.close()
            finished.append(True)
            if len(finished) == 2:
                done.set()

    output.subscribe(CloseTogether())
    first_callback = audio.listeners[10]
    audio.device = 20
    output.subscribe(CloseTogether())
    second_callback = audio.listeners[20]
    first_callback()
    second_callback()
    assert done.wait(1), "Observers waited on each other during adapter.close()"
    assert audio.listeners == {}

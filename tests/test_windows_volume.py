from queue import Queue
from threading import Event, Thread, get_ident

import pytest
from output_volume_contract import OutputVolumeContract

from opendeck import Observer
from opendeck.adapters.windows_volume import WindowsOutputVolume
from opendeck.volume import VolumeError, VolumeFailure


class FakeAudio:
    def __init__(self) -> None:
        self.level = 0.5
        self.muted = False
        self.status = 0
        self.calls = []
        self.watches = []

    def _read_output_volume(self):
        return self.status, self.level

    def _read_output_mute(self):
        return self.status, self.muted

    def _set_output_volume(self, level):
        self.calls.append(("volume", level))
        self.level = level
        return self.status

    def _set_output_mute(self, muted):
        self.calls.append(("mute", muted))
        self.muted = muted
        return self.status

    def _WindowsVolumeWatch(self):
        watch = FakeWatch()
        self.watches.append(watch)
        return watch


class FakeWatch:
    def __init__(self):
        self.events = Queue()
        self.threads = []
        self.closed = Event()
        self.start_status = 0
        self.refresh_status = 0
        self.close_status = 0

    def start(self):
        self.threads.append(get_ident())
        return self.start_status

    def wait(self):
        self.threads.append(get_ident())
        return self.events.get(timeout=3)

    def refresh(self):
        self.threads.append(get_ident())
        return self.refresh_status

    def cancel(self):
        self.events.put((0, False))

    def close(self):
        self.threads.append(get_ident())
        self.closed.set()
        return self.close_status


class Changes(Observer):
    def __init__(self):
        self.ready = Event()
        self.calls = 0

    def on_change(self):
        self.calls += 1
        self.ready.set()


@pytest.fixture
def api():
    return FakeAudio()


@pytest.fixture
def output(api):
    output = WindowsOutputVolume(api)
    yield output
    output.close()


@pytest.fixture
def notify_external_mute(api):
    def change(muted):
        api.muted = muted
        for watch in api.watches:
            watch.events.put((0, True))

    return change


class TestWindowsOutputVolumeContract(OutputVolumeContract):
    pass


def test_windows_output_reads_and_changes_the_selected_default():
    api = FakeAudio()
    output = WindowsOutputVolume(api)
    output.set_volume(0.25)
    output.set_mute(True)
    assert output.read_volume() == 0.25
    assert output.read_mute() is True
    assert api.calls == [("volume", 0.25), ("mute", True)]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (0x80070490, VolumeFailure.NO_OUTPUT),
        (0x88890004, VolumeFailure.NO_OUTPUT),
        (0x80004002, VolumeFailure.UNSUPPORTED),
        (0x80070005, VolumeFailure.PERMISSION_DENIED),
        (0x80004005, VolumeFailure.FAILED),
    ],
)
def test_windows_output_reports_hresult_failures(status, reason):
    api = FakeAudio()
    api.status = status
    output = WindowsOutputVolume(api)
    with pytest.raises(VolumeError) as error:
        output.read_volume()
    assert error.value.reason is reason
    assert f"0x{status:08X}" in str(error.value)


@pytest.mark.parametrize("level", [float("nan"), float("inf"), -1, 1.1, True])
def test_windows_output_rejects_invalid_volume_before_native_calls(level):
    api = FakeAudio()
    output = WindowsOutputVolume(api)
    with pytest.raises(ValueError):
        output.set_volume(level)
    assert api.calls == []


def test_windows_notification_owns_com_work_on_one_worker_thread(api):
    output = WindowsOutputVolume(api)
    changes = Changes()
    unsubscribe = output.subscribe(changes)
    watch = api.watches[0]
    watch.events.put((0, True))
    assert changes.ready.wait(3)
    unsubscribe()
    unsubscribe()
    assert watch.closed.is_set()
    assert len(set(watch.threads)) == 1
    assert watch.threads[0] != get_ident()
    output.close()


def test_windows_subscription_start_failure_is_reported_and_closed(api):
    watch = FakeWatch()
    watch.start_status = 0x80070005
    api._WindowsVolumeWatch = lambda: watch
    output = WindowsOutputVolume(api)
    with pytest.raises(VolumeError) as error:
        output.subscribe(Changes())
    assert error.value.reason is VolumeFailure.PERMISSION_DENIED
    assert watch.closed.is_set()
    output.close()


def test_close_during_subscription_start_cancels_the_created_watch(api):
    entered, release = Event(), Event()
    watch = FakeWatch()
    errors = []

    def create():
        entered.set()
        assert release.wait(3)
        return watch

    api._WindowsVolumeWatch = create
    output = WindowsOutputVolume(api)
    starting = Thread(target=lambda: output.subscribe(Changes()))
    starting.start()
    assert entered.wait(3)

    def close():
        try:
            output.close()
        except Exception as error:  # codex-rule-ignore: assert racing close outcome
            errors.append(error)

    closing = Thread(target=close)
    closing.start()
    release.set()
    starting.join(3)
    closing.join(3)
    assert not starting.is_alive()
    assert not closing.is_alive()
    assert watch.closed.is_set()
    assert errors == []


def test_native_cleanup_failure_can_be_retried_by_the_adapter(api):
    output = WindowsOutputVolume(api)
    unsubscribe = output.subscribe(Changes())
    watch = api.watches[0]
    watch.close_status = 0x80004005
    with pytest.raises(VolumeError, match="Close output notification"):
        unsubscribe()
    watch.close_status = 0
    output.close()
    assert watch.closed.is_set()
    assert len(set(watch.threads)) == 1


def test_observer_teardown_is_rejected_without_cross_worker_waits(api):
    output = WindowsOutputVolume(api)
    attempted = Event()
    errors = []

    class Closing(Observer):
        def on_change(self):
            try:
                output.close()
            except RuntimeError as error:  # codex-rule-ignore: assert owner guard
                errors.append(str(error))
                attempted.set()

    output.subscribe(Closing())
    output.subscribe(Changes())
    api.watches[0].events.put((0, True))
    assert attempted.wait(3)
    output.close()
    assert errors == ["Schedule audio unsubscribe on the application owner"]
    assert all(watch.closed.is_set() for watch in api.watches)


@pytest.mark.parametrize("level", [float("nan"), float("inf"), -1.0, 1.1])
def test_invalid_windows_volume_is_reported_as_failure(level):
    api = FakeAudio()
    api.level = level
    with pytest.raises(VolumeError, match="Invalid Windows volume value"):
        WindowsOutputVolume(api).read_volume()


def test_rebind_failure_notifies_without_poisoning_reads_and_can_recover(api):
    output = WindowsOutputVolume(api)
    changes = Changes()
    unsubscribe = output.subscribe(changes)
    watch = api.watches[0]
    watch.refresh_status = 0x88890004
    watch.events.put((0, True))
    assert changes.ready.wait(3)
    assert output.read_volume() == 0.5
    changes.ready.clear()
    watch.refresh_status = 0
    watch.events.put((0, True))
    assert changes.ready.wait(3)
    unsubscribe()
    output.close()


def test_unresolved_rebind_error_is_reported_after_native_cleanup(api):
    output = WindowsOutputVolume(api)
    changes = Changes()
    unsubscribe = output.subscribe(changes)
    watch = api.watches[0]
    watch.refresh_status = 0x80004005
    watch.events.put((0, True))
    assert changes.ready.wait(3)
    with pytest.raises(VolumeError, match="Refresh output notification"):
        unsubscribe()
    assert watch.closed.is_set()
    output.close()


def test_wait_failure_is_retained_until_the_owner_releases_subscription(api):
    output = WindowsOutputVolume(api)
    unsubscribe = output.subscribe(Changes())
    watch = api.watches[0]
    watch.events.put((0x80004005, False))
    assert watch.closed.wait(3)
    with pytest.raises(VolumeError, match="Wait for output notification"):
        unsubscribe()
    output.close()


def test_partial_start_and_failed_cleanup_remain_owned_for_retry(api):
    watch = FakeWatch()
    watch.start_status = 0x80070005
    watch.close_status = 0x80004005
    api._WindowsVolumeWatch = lambda: watch
    output = WindowsOutputVolume(api)
    with pytest.raises(VolumeError) as error:
        output.subscribe(Changes())
    assert error.value.reason is VolumeFailure.PERMISSION_DENIED
    assert "Close output notification" in error.value.__notes__[0]
    watch.close_status = 0
    output.close()
    assert len(set(watch.threads)) == 1


def test_worker_start_failure_acquires_no_native_watch(api, monkeypatch):
    def reject(_):
        raise RuntimeError("cannot start new thread")

    monkeypatch.setattr(Thread, "start", reject)
    output = WindowsOutputVolume(api)
    with pytest.raises(RuntimeError, match="cannot start"):
        output.subscribe(Changes())
    assert api.watches == []
    output.close()


def test_closed_adapter_rejects_new_subscriptions(api):
    output = WindowsOutputVolume(api)
    output.close()
    with pytest.raises(VolumeError, match="adapter is closed"):
        output.subscribe(Changes())
    assert api.watches == []


def test_observer_bug_is_preserved_and_all_subscriptions_are_released(api):
    failure = ValueError("observer bug")

    class Broken(Observer):
        def on_change(self):
            raise failure

    output = WindowsOutputVolume(api)
    output.subscribe(Broken())
    output.subscribe(Changes())
    api.watches[0].events.put((0, True))
    assert api.watches[0].closed.wait(3)
    with pytest.raises(ValueError) as error:
        output.close()
    assert error.value is failure
    assert all(watch.closed.is_set() for watch in api.watches)
    output.close()


def test_default_constructor_reports_unsupported_outside_windows(monkeypatch):
    import opendeck.adapters.windows_volume as windows

    monkeypatch.setattr(windows.sys, "platform", "darwin")
    with pytest.raises(VolumeError) as error:
        WindowsOutputVolume()
    assert error.value.reason is VolumeFailure.UNSUPPORTED

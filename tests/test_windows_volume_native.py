import ctypes
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Core Audio")


def test_native_readers_return_status_and_typed_values_without_mutating_output():
    from opendeck import _native

    volume_status, volume = _native._read_output_volume()
    mute_status, muted = _native._read_output_mute()
    assert 0 <= volume_status <= 0xFFFFFFFF
    assert 0 <= mute_status <= 0xFFFFFFFF
    if volume_status == 0:
        assert 0.0 <= volume <= 1.0
    if mute_status == 0:
        assert isinstance(muted, bool)


def test_native_watch_cancel_wakes_owner_and_releases_registrations():
    script = textwrap.dedent("""
        from concurrent.futures import ThreadPoolExecutor
        from opendeck import _native
        watch = _native._WindowsVolumeWatch()
        def run():
            try:
                assert watch.start() == 0
                while True:
                    status, changed = watch.wait()
                    assert status == 0
                    if not changed:
                        break
                    watch.refresh()
            finally:
                assert watch.close() == 0
                assert watch.close() == 0
        with ThreadPoolExecutor(max_workers=1) as executor:
            stopped = executor.submit(run)
            watch.cancel()
            stopped.result(timeout=10)
        """)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr


def test_native_reader_borrows_the_callers_existing_sta_apartment():
    from opendeck import _native

    def read_from_sta():
        ole = ctypes.OleDLL("ole32")
        ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole.CoInitializeEx.restype = ctypes.c_long
        ole.CoGetApartmentType.argtypes = [
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        ole.CoGetApartmentType.restype = ctypes.c_long
        ole.CoUninitialize.argtypes = []
        ole.CoUninitialize.restype = None
        assert ole.CoInitializeEx(None, 2) in (0, 1)
        try:
            status, _ = _native._read_output_volume()
            assert status != 0x80010106  # RPC_E_CHANGED_MODE
            kind = ctypes.c_int()
            qualifier = ctypes.c_int()
            result = ole.CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qualifier))
            assert result == 0
            assert kind.value == 0  # APTTYPE_STA
        finally:
            ole.CoUninitialize()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(read_from_sta).result(timeout=10)


def test_native_readers_survive_the_other_mta_owners_shutdown():
    script = textwrap.dedent("""
        import ctypes
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from opendeck import _native
        ready, stop = Event(), Event()
        def owner():
            ole = ctypes.OleDLL('ole32')
            assert ole.CoInitializeEx(None, 0) in (0, 1)
            try:
                ready.set()
                assert stop.wait(5)
            finally:
                ole.CoUninitialize()
        def read():
            assert ready.wait(5)
            try:
                statuses = [_native._read_output_volume()[0]]
                stop.set()
                statuses += [_native._read_output_volume()[0] for _ in range(16)]
                assert 0x800401F0 not in statuses
            finally:
                stop.set()
        with ThreadPoolExecutor(max_workers=2) as executor:
            source = executor.submit(owner)
            executor.submit(read).result(timeout=10)
            source.result(timeout=10)
        """)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr

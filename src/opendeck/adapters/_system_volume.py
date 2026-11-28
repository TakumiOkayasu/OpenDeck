"""Select and own the OS adapter for the default audio output."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager

from ..volume import OutputVolume, VolumeError, VolumeFailure


@contextmanager
def system_output() -> Iterator[OutputVolume]:
    if sys.platform == "win32":
        from .windows_volume import WindowsOutputVolume

        adapter = WindowsOutputVolume()
    elif sys.platform == "darwin":
        from .macos_volume import MacOSOutputVolume

        adapter = MacOSOutputVolume()
    else:
        raise VolumeError(VolumeFailure.UNSUPPORTED, "Windows or macOS is required")
    try:
        yield adapter
    finally:
        adapter.close()

import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pybind11
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "configure_clangd.py"


def test_clangd_configure_uses_persistent_python_and_all_native_targets(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    with patch("subprocess.run") as run:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    run.assert_called_once_with(
        [
            "cmake",
            "--fresh",
            "-S",
            str(ROOT),
            "-B",
            str(ROOT / "build" / "clangd"),
            "-G",
            "Ninja",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            "-DCMAKE_BUILD_TYPE=Debug",
            "-DOPENDECK_BUILD_PYTHON=ON",
            "-DBUILD_TESTING=ON",
            f"-DPython_EXECUTABLE={sys.executable}",
            f"-Dpybind11_DIR={pybind11.get_cmake_dir()}",
        ],
        check=True,
    )


def test_clangd_configure_does_not_hide_cmake_failure():
    error = subprocess.CalledProcessError(1, "cmake")
    with (
        patch("subprocess.run", side_effect=error),
        pytest.raises(subprocess.CalledProcessError),
    ):
        runpy.run_path(str(SCRIPT), run_name="__main__")

import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import call, patch

import pybind11
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "configure_clangd.py"


@pytest.mark.parametrize("platform, suffix", [("win32", ".exe"), ("linux", "")])
def test_clangd_configure_uses_persistent_python_and_all_native_targets(
    tmp_path, monkeypatch, platform, suffix
):
    monkeypatch.chdir(tmp_path)
    ninja = str(tmp_path / "Build Tools" / "ninja.exe")
    compiler = str(tmp_path / "Build Tools" / "clang++.exe")
    with (
        patch("subprocess.run") as run,
        patch("shutil.which", side_effect=[ninja, compiler]) as which,
        patch("sys.platform", platform),
    ):
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert which.call_args_list == [call(f"ninja{suffix}"), call(f"clang++{suffix}")]
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
            f"-DCMAKE_MAKE_PROGRAM={ninja}",
            f"-DCMAKE_CXX_COMPILER={compiler}",
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
        patch("shutil.which", side_effect=["/tools/ninja", "/tools/clang++"]),
        pytest.raises(subprocess.CalledProcessError),
    ):
        runpy.run_path(str(SCRIPT), run_name="__main__")


def test_clangd_configure_requires_ninja_before_running_cmake():
    with (
        patch("subprocess.run") as run,
        patch("shutil.which", return_value=None),
        pytest.raises(SystemExit, match="Ninja"),
    ):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    run.assert_not_called()


def test_clangd_configure_requires_clang_before_running_cmake():
    with (
        patch("subprocess.run") as run,
        patch("shutil.which", side_effect=["/tools/ninja", None]),
        pytest.raises(SystemExit, match="Clang"),
    ):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    run.assert_not_called()

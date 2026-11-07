"""Generate clangd commands with the development environment's Python headers."""

import shutil
import subprocess
import sys
from pathlib import Path

import pybind11


def main():
    root = Path(__file__).resolve().parents[1]
    ninja = shutil.which("ninja.exe" if sys.platform == "win32" else "ninja")
    if ninja is None:
        raise SystemExit("Ninja not found. Run with mise exec --.")
    subprocess.run(
        [
            "cmake",
            "--fresh",
            "-S",
            str(root),
            "-B",
            str(root / "build" / "clangd"),
            "-G",
            "Ninja",
            f"-DCMAKE_MAKE_PROGRAM={ninja}",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            "-DCMAKE_BUILD_TYPE=Debug",
            "-DOPENDECK_BUILD_PYTHON=ON",
            "-DBUILD_TESTING=ON",
            f"-DPython_EXECUTABLE={sys.executable}",
            f"-Dpybind11_DIR={pybind11.get_cmake_dir()}",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()

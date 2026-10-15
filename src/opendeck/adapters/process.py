import subprocess

from ..model import Result, Status


class Processes:
    def start(self, argv: tuple[str, ...]) -> Result:
        try:
            process = subprocess.Popen(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            return Result(Status.FAILED, str(error))
        return Result(Status.DONE, f"pid={process.pid}")

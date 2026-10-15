from dataclasses import dataclass
from typing import Protocol

from .model import Result


class Start(Protocol):
    def start(self, argv: tuple[str, ...]) -> Result: ...


@dataclass(frozen=True, slots=True)
class Launch:
    argv: tuple[str, ...]
    target: Start

    def run(self) -> Result:
        return self.target.start(self.argv)

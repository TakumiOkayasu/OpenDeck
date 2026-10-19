from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .model import Result
from .ports import Action


class Start(Protocol):
    def start(self, argv: tuple[str, ...]) -> Result: ...


@dataclass(frozen=True, slots=True)
class Launch(Action):
    argv: tuple[str, ...]
    target: Start

    def run(self) -> Result:
        return self.target.start(self.argv)


@dataclass(frozen=True, slots=True)
class LaunchBuilder:
    target: Start

    def __call__(self, options: Mapping[str, object]) -> Launch:
        required = {"argv"}
        keys = set(options)
        if keys != required:
            raise ValueError(
                f"missing={sorted(required - keys)}, unknown={sorted(keys - required)}"
            )
        argv = options["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
            or not argv[0]
        ):
            raise ValueError("expected a nonempty argument list")
        return Launch(tuple(argv), self.target)

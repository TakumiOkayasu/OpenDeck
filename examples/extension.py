from collections.abc import Callable, Mapping
from dataclasses import dataclass

from opendeck import Action, Binding, Input, Result, Slot, Status
from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.config import parse
from opendeck.runtime import drain

PRIMARY = Slot("primary")


@dataclass(frozen=True, slots=True)
class Record:
    text: str
    write: Callable[[str], None]

    def run(self) -> Result:
        self.write(self.text)
        return Result(Status.DONE)


def dispatch(input: Input[Slot], binding: Binding) -> int:
    def report(slot: Slot, result: Result | None) -> None:
        status = "unassigned" if result is None else result.status.value
        print(f"{slot}: {status}")

    return drain(input, binding, report)


def main() -> None:
    messages: list[str] = []

    def build(options: Mapping[str, object]) -> Action:
        if set(options) != {"text"} or not isinstance(options["text"], str):
            raise ValueError("expected only a text string")
        return Record(options["text"], messages.append)

    settings = parse(
        {
            "inputs": [PRIMARY],
            "chords": [],
            "device": {"keys": {"1": PRIMARY}},
            "actions": {
                "remember": {"kind": "record", "text": "recorded by extension"}
            },
            "bindings": {PRIMARY: "remember"},
        },
        {"record": build},
    )
    product = ReplayFactory(
        settings.keys, settings.chords, (Edge(1, True), Edge(1, False))
    ).make()
    try:
        product.link.open()
        dispatch(product.input, settings.binding)
    finally:
        product.link.close()
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()

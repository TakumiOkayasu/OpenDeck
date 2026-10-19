from opendeck import Change, Input, Read, Slot, input_view, read_view
from opendeck.adapters.replay import Edge, ReplayFactory


def receive(state: Read[bool], changes: Input[Change]) -> None:
    while (change := changes.take()) is not None:
        print(f"pressed={change.pressed} at={change.at}")
    print(f"current={state.read()}")


def main() -> None:
    primary = Slot("primary")
    times = iter((1.0, 2.0))
    product = ReplayFactory(
        {1: primary}, (), (Edge(1, True), Edge(1, False))
    ).make_buttons(clock=lambda: next(times))
    try:
        product.link.open()
        button = product.buttons[primary]
        receive(read_view(button), input_view(button))
    finally:
        product.link.close()


if __name__ == "__main__":
    main()

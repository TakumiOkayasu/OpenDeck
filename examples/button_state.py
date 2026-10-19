from opendeck import Button, Slot
from opendeck.adapters.replay import Edge, ReplayFactory


def receive(button: Button) -> None:
    while (change := button.take()) is not None:
        print(f"pressed={change.pressed} at={change.at}")
    print(f"current={button.read()}")


def main() -> None:
    primary = Slot("primary")
    times = iter((1.0, 2.0))
    product = ReplayFactory(
        {1: primary}, (), (Edge(1, True), Edge(1, False))
    ).make_buttons(clock=lambda: next(times))
    try:
        product.link.open()
        receive(product.buttons[primary])
    finally:
        product.link.close()


if __name__ == "__main__":
    main()

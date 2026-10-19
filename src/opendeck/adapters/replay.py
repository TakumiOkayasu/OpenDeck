from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import monotonic
from types import MappingProxyType

from ..model import Chord, Slot
from ..ports import ButtonFactory, ButtonProduct, Factory, Link, Product
from ..recognition import validate_adaptation
from ..source import Source
from .inputs import Panel, Receiver, Signals


@dataclass(frozen=True, slots=True)
class Edge:
    key: int
    pressed: bool


def parse_events(value: object) -> tuple[Edge, ...]:
    if not isinstance(value, list):
        raise ValueError("events: expected a list")
    result = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, dict)
            or set(item) != {"key", "pressed"}
            or type(item["key"]) is not int
            or item["key"] <= 0
            or type(item["pressed"]) is not bool
        ):
            raise ValueError(f"events[{index}]: expected key and pressed")
        result.append(Edge(item["key"], item["pressed"]))
    return tuple(result)


class Replay(Link):
    def __init__(
        self,
        receiver: Receiver,
        keys: Mapping[int, Slot],
        events: tuple[Edge, ...],
    ) -> None:
        self._receiver = receiver
        self._keys = dict(keys)
        self._events = events

    def open(self) -> None:
        self._receiver.start()
        for edge in self._events:
            slot = self._keys.get(edge.key)
            if slot is None:
                continue
            try:
                accepted, observers = self._receiver.receive(slot, edge.pressed)
            except Exception as error:
                Source.notify(self._receiver.record_failure(error))
                raise
            Source.notify(observers)
            if not accepted:
                return

    def close(self) -> None:
        Source.notify(self._receiver.close())


@dataclass(frozen=True, slots=True)
class ReplayFactory(Factory, ButtonFactory):
    keys: Mapping[int, Slot]
    chords: tuple[Chord, ...]
    events: tuple[Edge, ...]

    def __post_init__(self) -> None:
        keys = MappingProxyType(dict(self.keys))
        chords = tuple(self.chords)
        validate_adaptation(tuple(keys.values()), chords)
        object.__setattr__(self, "keys", keys)
        object.__setattr__(self, "chords", chords)
        object.__setattr__(self, "events", tuple(self.events))

    def make(self) -> Product:
        source = Source[Slot](capacity=max(1, len(self.events)))
        link = Replay(Signals(source, self.chords), self.keys, self.events)
        return Product(link, source.input, source.subject)

    def make_buttons(self, *, clock: Callable[[], float] = monotonic) -> ButtonProduct:
        panel = Panel(
            self.keys.values(), self.chords, clock, capacity=max(1, len(self.events))
        )
        return ButtonProduct(Replay(panel, self.keys, self.events), panel.buttons)

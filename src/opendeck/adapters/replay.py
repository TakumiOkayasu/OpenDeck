from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..model import Chord, Slot
from ..ports import Product
from ..recognition import State, apply, validate_adaptation
from ..source import Source


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


class Replay:
    def __init__(
        self,
        source: Source[Slot],
        keys: Mapping[int, Slot],
        chords: tuple[Chord, ...],
        events: tuple[Edge, ...],
    ) -> None:
        self._source = source
        self._keys = dict(keys)
        self._chords = chords
        self._events = events
        self._state = State()

    def open(self) -> None:
        self._source.start()
        self._state = State()
        for edge in self._events:
            slot = self._keys.get(edge.key)
            if slot is None:
                continue
            self._state, signals = apply(self._state, slot, edge.pressed, self._chords)
            for signal in signals:
                if not self._source.publish(signal):
                    return

    def close(self) -> None:
        self._source.close()
        self._state = State()


@dataclass(frozen=True, slots=True)
class ReplayFactory:
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
        link = Replay(source, self.keys, self.chords, self.events)
        return Product(link, source, source)

from opendeck.adapters.replay import Edge, ReplayFactory
from opendeck.bindings import Binding
from opendeck.model import Result, Slot, Status
from opendeck.runtime import drain


def test_finite_replay_length_does_not_cause_artificial_live_queue_overflow():
    slot = Slot("repeated")
    calls = []

    class Action:
        def run(self):
            calls.append(None)
            return Result(Status.DONE)

    events = tuple(edge for _ in range(257) for edge in (Edge(1, True), Edge(1, False)))
    product = ReplayFactory({1: slot}, (), events).make()
    try:
        product.link.open()
        assert (
            drain(product.input, Binding({slot: Action()}), lambda *args: None) == 257
        )
        assert len(calls) == 257
    finally:
        product.link.close()

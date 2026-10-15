from opendeck.bindings import Binding
from opendeck.model import Result, Slot, Status
from opendeck.runtime import Wake, drain
from opendeck.source import Source


class CountingAction:
    def __init__(self, status=Status.DONE):
        self.calls = 0
        self.status = status

    def run(self):
        self.calls += 1
        return Result(self.status)


def test_coalesced_notification_preserves_repeated_inputs_and_unassigned():
    source = Source[Slot]()
    action = CountingAction()
    assigned, missing = Slot("assigned"), Slot("missing")
    binding = Binding({assigned: action})
    results = []
    wake = Wake()
    source.add(wake)
    source.start()
    for slot in (assigned, missing, assigned):
        source.publish(slot)
    wake.wait()
    assert drain(source, binding, lambda *args: results.append(args)) == 3
    assert action.calls == 2
    assert results == [
        (assigned, Result(Status.DONE)),
        (missing, None),
        (assigned, Result(Status.DONE)),
    ]
    assert source.take() is None


def test_failed_or_unknown_operations_are_reported_once_without_retry():
    source = Source[Slot]()
    failed, unknown = Slot("failed"), Slot("unknown")
    actions = {
        failed: CountingAction(Status.FAILED),
        unknown: CountingAction(Status.UNKNOWN),
    }
    source.start()
    source.publish(failed)
    source.publish(unknown)
    results = []
    drain(source, Binding(actions), lambda *args: results.append(args))
    assert [result.status for _, result in results] == [Status.FAILED, Status.UNKNOWN]
    assert [action.calls for action in actions.values()] == [1, 1]


def test_input_already_handed_over_survives_origin_close():
    source = Source[Slot]()
    slot = Slot("independent")
    action = CountingAction()
    source.start()
    source.publish(slot)
    received = source.take()
    source.close()
    assert received is not None
    chosen = Binding({slot: action}).select(received)
    assert chosen is not None
    assert chosen.run().status is Status.DONE
    assert action.calls == 1

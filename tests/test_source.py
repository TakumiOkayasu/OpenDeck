from threading import Event, Lock, Thread

import pytest

from opendeck.source import InputError, Source


class Counter:
    def __init__(self) -> None:
        self.calls = 0

    def on_change(self) -> None:
        self.calls += 1


def test_fifo_preserves_all_occurrences_including_duplicate_values() -> None:
    source = Source[str]()
    source.start()
    assert source.publish("a")
    assert source.publish("a")
    assert source.publish("b")
    assert [source.take(), source.take(), source.take(), source.take()] == [
        "a",
        "a",
        "b",
        None,
    ]


def test_observers_are_deduplicated_and_removed_by_identity() -> None:
    class EqualCounter(Counter):
        def __eq__(self, other: object) -> bool:
            return True

    source = Source[str]()
    first, second = EqualCounter(), EqualCounter()
    source.add(first)
    source.add(first)
    source.add(second)
    source.start()
    source.publish("a")
    assert (first.calls, second.calls) == (1, 1)
    source.remove(first)
    source.remove(first)
    source.publish("b")
    assert (first.calls, second.calls) == (1, 2)


def test_notification_allows_reentrant_take_and_remove_without_deadlock() -> None:
    source = Source[str]()
    received: list[str | None] = []

    class Reader:
        def on_change(self) -> None:
            received.append(source.take())
            source.remove(self)

    source.add(Reader())
    source.start()
    thread = Thread(target=source.publish, args=("a",), daemon=True)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive(), "Observer ran while the input lock was held"
    assert received == ["a"]


def test_new_observer_is_notified_of_existing_pending_input() -> None:
    source = Source[str]()
    source.start()
    source.publish("a")
    observer = Counter()
    source.add(observer)
    assert observer.calls == 1
    assert source.take() == "a"


def test_overflow_is_observable_and_does_not_deliver_a_partial_sequence() -> None:
    source = Source[str](capacity=2)
    observer = Counter()
    source.add(observer)
    source.start()
    source.publish("a")
    source.publish("b")
    assert not source.publish("c")
    assert observer.calls == 3
    assert not source.publish("d")
    with pytest.raises(InputError, match="capacity"):
        source.take()
    source.close()
    with pytest.raises(InputError, match="capacity"):
        source.take()
    source.start()
    assert source.take() is None
    assert source.publish("new")
    assert source.take() == "new"


def test_transport_failure_clears_pending_input_and_notifies() -> None:
    source = Source[str]()
    observer = Counter()
    source.add(observer)
    source.start()
    source.publish("pending")
    source.fail(OSError("disconnected"))
    assert observer.calls == 2
    with pytest.raises(InputError, match="disconnected"):
        source.take()
    assert not source.publish("stale")


def test_close_discards_unhanded_input_and_reopen_starts_clean() -> None:
    source = Source[str]()
    assert not source.publish("before-open")
    source.start()
    source.publish("pending")
    source.close()
    assert source.take() is None
    assert not source.publish("after-close")
    source.start()
    assert source.take() is None


def test_close_between_notification_and_take_prevents_stale_delivery() -> None:
    source = Source[str]()
    received: list[str | None] = []

    class ClosingReader:
        def on_change(self) -> None:
            source.close()
            received.append(source.take())

    source.add(ClosingReader())
    source.start()
    source.publish("pending")
    assert received == [None]
    assert not source.publish("after-close")


def test_invalid_capacity_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        Source(capacity=0)


def test_concurrent_close_clears_input_before_a_delayed_observer_consumes() -> None:
    source = Source[str]()
    notified = Event()
    resume = Event()
    received: list[str | None] = []

    class DelayedReader:
        def on_change(self) -> None:
            notified.set()
            if resume.wait(timeout=2):
                received.append(source.take())

    source.add(DelayedReader())
    source.start()
    publisher = Thread(target=source.publish, args=("pending",), daemon=True)
    publisher.start()
    assert notified.wait(timeout=2)
    source.close()
    resume.set()
    publisher.join(timeout=2)
    assert not publisher.is_alive()
    assert received == [None]


def test_staged_notification_runs_outside_the_callers_lock() -> None:
    source = Source[str]()
    adapter_lock = Lock()
    received: list[str | None] = []

    class Reader:
        def on_change(self) -> None:
            assert adapter_lock.acquire(blocking=False), "Adapter lock is still held"
            try:
                received.append(source.take())
            finally:
                adapter_lock.release()

    source.add(Reader())
    source.start()
    with adapter_lock:
        accepted, observers = source.enqueue("a")
        assert received == []
    source.notify(observers)
    assert accepted
    assert received == ["a"]


def test_close_after_enqueue_before_notification_prevents_stale_delivery() -> None:
    source = Source[str]()
    received: list[str | None] = []

    class Reader:
        def on_change(self) -> None:
            received.append(source.take())

    source.add(Reader())
    source.start()
    accepted, observers = source.enqueue("a")
    source.close()
    source.notify(observers)
    assert accepted
    assert received == [None]


def test_staged_failure_does_not_call_observers_before_notification() -> None:
    source = Source[str]()
    observer = Counter()
    source.add(observer)
    source.start()
    source.enqueue("pending")
    observers = source.record_failure("disconnected")
    assert observer.calls == 0
    with pytest.raises(InputError, match="disconnected"):
        source.take()
    source.notify(observers)
    assert observer.calls == 1


def test_staged_overflow_notifies_failure_after_queue_mutation() -> None:
    source = Source[str](capacity=1)
    observer = Counter()
    source.add(observer)
    source.start()
    source.enqueue("pending")
    accepted, observers = source.enqueue("overflow")
    assert not accepted
    assert observer.calls == 0
    source.notify(observers)
    assert observer.calls == 1
    with pytest.raises(InputError, match="capacity"):
        source.take()

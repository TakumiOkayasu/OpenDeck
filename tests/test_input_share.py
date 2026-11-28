import asyncio
from contextlib import asynccontextmanager, suppress

import pytest

from opendeck.host import InputShare
from opendeck.model import Change
from opendeck.ports import InputError, Observer
from opendeck.source import Source


class Notice(Observer):
    def __init__(self, count=1):
        self.ready = asyncio.Event()
        self.remaining = count

    def on_change(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self.ready.set()


@asynccontextmanager
async def listening(share):
    ready = asyncio.Event()
    listener = asyncio.create_task(share.listen(on_ready=ready.set))
    try:
        await ready.wait()
        yield listener
    finally:
        listener.cancel()
        with suppress(asyncio.CancelledError):
            await listener


def test_shared_changes_are_consumed_independently_by_selected_recipients():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        first = share.subscribe(capacity=2)
        second = share.subscribe(capacity=2)
        notice = Notice()
        second.subject.add(notice)
        change = Change(True, 1.5)
        async with listening(share):
            source.publish(change)
            await notice.ready.wait()
            assert first.input.take() == change
            assert first.input.take() is None
            assert second.input.take() == change
            assert second.input.take() is None
            assert not hasattr(first.input, "publish")
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_unsubscribe_discards_pending_changes_and_new_subscription_gets_next_change():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        old = share.subscribe(capacity=2)
        notice = Notice()
        old.subject.add(notice)
        async with listening(share):
            source.publish(Change(True, 1.0))
            await notice.ready.wait()
            old.close()
            old.close()
            with pytest.raises(InputError, match="closed"):
                old.input.take()
            replacement = share.subscribe(capacity=1)
            assert replacement.input.take() is None
            replacement.subject.add(notice)
            notice.ready.clear()
            source.publish(Change(False, 2.0))
            await notice.ready.wait()
            assert replacement.input.take() == Change(False, 2.0)
            with pytest.raises(InputError, match="closed"):
                old.input.take()
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_stopping_listener_invalidates_subscriptions_and_forbids_restart():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        recipient = share.subscribe(capacity=1)
        async with listening(share):
            accepted, pending = source.enqueue(Change(True, 1.0))
            assert accepted
        with pytest.raises(InputError, match="stopped"):
            recipient.input.take()
        with pytest.raises(RuntimeError, match="stopped"):
            share.subscribe(capacity=1)
        with pytest.raises(RuntimeError, match="stopped"):
            await share.listen()
        source.notify(pending)
        assert source.enqueue(Change(False, 2.0))[1] == ()
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_upstream_failure_invalidates_every_recipient_with_its_cause():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        recipients = [share.subscribe(capacity=2) for _ in range(2)]
        ready = asyncio.Event()
        listener = asyncio.create_task(share.listen(on_ready=ready.set))
        await ready.wait()
        source.fail("disconnected")
        with pytest.raises(InputError, match="disconnected"):
            await listener
        for recipient in recipients:
            with pytest.raises(InputError, match="disconnected"):
                recipient.input.take()
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_a_second_listener_is_rejected_without_disrupting_the_first():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        recipient = share.subscribe(capacity=1)
        notice = Notice()
        recipient.subject.add(notice)
        async with listening(share):
            with pytest.raises(RuntimeError, match="already listening"):
                await asyncio.wait_for(share.listen(), 0.1)
            source.publish(Change(True, 1.0))
            await notice.ready.wait()
            assert recipient.input.take() == Change(True, 1.0)
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_a_full_recipient_queue_fails_independently_and_retains_no_partial_changes():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        slow = share.subscribe(capacity=1)
        fast = share.subscribe(capacity=1)
        notice = Notice()
        fast.subject.add(notice)
        async with listening(share):
            for change in (Change(True, 1.0), Change(False, 2.0), Change(True, 3.0)):
                notice.ready.clear()
                source.publish(change)
                await notice.ready.wait()
                assert fast.input.take() == change
            with pytest.raises(InputError, match="capacity"):
                slow.input.take()
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_startup_backlog_is_delivered_in_order_while_yielding_to_a_ready_peer():
    async def check():
        source = Source[Change]()
        source.start()
        changes = [Change(True, 1.0), Change(False, 2.0), Change(True, 3.0)]
        for change in changes:
            source.publish(change)
        share = InputShare(source.input, source.subject)
        recipient = share.subscribe(capacity=3)
        notice = Notice(count=3)
        recipient.subject.add(notice)
        observed = []
        loop = asyncio.get_running_loop()
        listener = asyncio.create_task(
            share.listen(
                on_ready=lambda: loop.call_soon(
                    lambda: observed.append(recipient.input.take())
                )
            )
        )
        try:
            await notice.ready.wait()
            assert observed == changes[:1]
            assert [recipient.input.take(), recipient.input.take()] == changes[1:]
        finally:
            listener.cancel()
            with suppress(asyncio.CancelledError):
                await listener
            source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_worker_thread_notifications_wake_the_share_but_cannot_change_subscriptions():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        recipient = share.subscribe(capacity=1)
        notice = Notice()
        recipient.subject.add(notice)
        async with listening(share):
            await asyncio.to_thread(source.publish, Change(True, 1.0))
            await notice.ready.wait()
            assert recipient.input.take() == Change(True, 1.0)
            with pytest.raises(RuntimeError):
                await asyncio.to_thread(share.subscribe, capacity=1)
            with pytest.raises(RuntimeError):
                await asyncio.to_thread(recipient.close)
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_cancelled_listener_ignores_notifications_delayed_until_after_loop_close():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        async with listening(share):
            accepted, pending = source.enqueue(Change(True, 1.0))
            assert accepted
            assert len(pending) == 1
        return source, pending

    source, pending = asyncio.run(asyncio.wait_for(check(), 3))
    source.notify(pending)
    assert source.enqueue(Change(False, 2.0))[1] == ()
    source.close()


def test_stopping_allows_a_queued_payload_finalizer_to_close_its_subscription():
    async def check():
        source = Source[object]()
        source.start()
        share = InputShare(source.input, source.subject)
        first = share.subscribe(capacity=2)
        second = share.subscribe(capacity=2)
        notice = Notice(count=2)
        second.subject.add(notice)
        finalized = []

        class ClosingPayload:
            def __del__(self):
                first.close()
                finalized.append("closed")

        async with listening(share):
            source.publish(ClosingPayload())
            source.publish(object())
            await notice.ready.wait()
        assert finalized == ["closed"]
        for recipient in (first, second):
            with pytest.raises(InputError, match="stopped"):
                recipient.input.take()
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))


def test_recipient_notification_error_is_distinct_from_upstream_failure():
    async def check():
        source = Source[Change]()
        source.start()
        share = InputShare(source.input, source.subject)
        recipient = share.subscribe(capacity=1)

        class FailingNotice(Observer):
            def on_change(self):
                recipient.subject.remove(self)
                raise InputError("recipient notification failed")

        recipient.subject.add(FailingNotice())
        ready = asyncio.Event()
        listener = asyncio.create_task(share.listen(on_ready=ready.set))
        await ready.wait()
        source.publish(Change(True, 1.0))
        with pytest.raises(InputError, match="recipient notification failed"):
            await listener
        with pytest.raises(InputError, match="sharing stopped"):
            recipient.input.take()
        source.close()

    asyncio.run(asyncio.wait_for(check(), 3))

import asyncio

import pytest

from opendeck.host import AsyncHost, Resource
from opendeck.model import Result, Slot, Status
from opendeck.ports import View

A, B, OTHER = Slot("a"), Slot("b"), Slot("other")
DONE = Result(Status.DONE)


class Callback:
    def __init__(self, run):
        self.run = run


def test_shared_action_runs_in_order_while_another_action_can_finish():
    async def check():
        resumed = asyncio.Event()
        calls = []
        results = []

        async def first():
            calls.append("start")
            if len(calls) == 1:
                await resumed.wait()
                return Result(Status.FAILED)
            return DONE

        async def second():
            assert calls == ["start"]
            resumed.set()
            return DONE

        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, lambda *args: results.append(args), pending_limit=2)
            shared = Callback(first)
            host.bind(shared, [A])
            host.bind(shared, [OTHER])
            host.bind(Callback(second), [B])
            for slot in (A, OTHER, B):
                host.dispatch(slot)
        assert calls == ["start", "start"]
        assert results == [(B, DONE), (A, Result(Status.FAILED)), (OTHER, DONE)]

    asyncio.run(asyncio.wait_for(check(), 3))


def test_overlapping_assignment_is_atomic_and_revoked_view_cannot_draw():
    async def check():
        images = []

        class Screen(View):
            def draw(self, image):
                images.append(image)

        resources = {
            "sub": Resource(frozenset({"sub"}), Screen()),
            "screen": Resource(frozenset({"main", "sub"}), Screen()),
            "led": Resource(frozenset({"led"})),
        }

        async def unused():
            return DONE

        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, lambda *_: None, resources, pending_limit=1)
            old = host.bind(Callback(unused), [A], ["sub"])
            view = old.view("sub")
            with pytest.raises(ValueError, match="occupied"):
                host.bind(Callback(unused), [B], ["led", "screen"])
            host.bind(Callback(unused), [B], ["led"])
            old.unbind()
            new = host.bind(Callback(unused), [A], ["screen"])
            new.view("screen").draw(b"new")
            old.unbind()
            with pytest.raises(RuntimeError, match="unbound"):
                view.draw(b"stale")
        assert images == [b"new"]

    asyncio.run(check())


def test_rebind_during_await_reports_stale_draw_and_skips_old_queued_action():
    async def check():
        images = []
        results = []
        resume = asyncio.Event()

        class Display(View):
            def draw(self, image):
                images.append(image)

        async def stale():
            await resume.wait()
            old_view.draw(b"old")
            return DONE

        async def replace():
            old.unbind()
            new = host.bind(Callback(fresh), [A], ["display"])
            new.view("display").draw(b"new")
            host.dispatch(A)
            resume.set()
            return DONE

        async def fresh():
            return DONE

        def report(slot, result):
            results.append((slot, result))
            if slot == B:
                replacement.unbind()

        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(
                tasks,
                report,
                {"display": Resource(frozenset({"pixels"}), Display())},
                pending_limit=2,
            )
            old = host.bind(Callback(stale), [A], ["display"])
            old_view = old.view("display")
            replacement = host.bind(Callback(replace), [B])
            for slot in (A, A, B):
                host.dispatch(slot)
        assert images == [b"new"]
        assert results.count((B, DONE)) == results.count((A, DONE)) == 1
        assert results.count((A, Result(Status.FAILED, "assignment is unbound"))) == 2

    asyncio.run(asyncio.wait_for(check(), 3))


def test_full_queue_reports_failure_and_keeps_accepted_input():
    async def check():
        results = []

        async def run():
            return DONE

        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, lambda *args: results.append(args), pending_limit=1)
            host.bind(Callback(run), [A])
            for slot in (A, A, B):
                host.dispatch(slot)
        assert results == [
            (A, Result(Status.FAILED, "action queue full")),
            (B, None),
            (A, DONE),
        ]

    asyncio.run(check())


def test_live_reader_wakes_from_another_thread_while_action_is_waiting():
    from opendeck.source import Source

    async def check():
        source = Source[Slot]()
        source.start()
        resume = asyncio.Event()
        started = asyncio.Event()
        finished = asyncio.Event()
        results = []

        async def first():
            started.set()
            await resume.wait()
            return DONE

        async def second():
            resume.set()
            return DONE

        def report(slot, result):
            results.append((slot, result))
            if slot == A:
                finished.set()

        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, report, pending_limit=1)
            host.bind(Callback(first), [A])
            host.bind(Callback(second), [B])
            source.publish(A)
            reader = tasks.create_task(host.listen(source, source))
            await started.wait()
            await asyncio.to_thread(source.publish, B)
            await finished.wait()
            reader.cancel()
        source.close()
        assert results == [(B, DONE), (A, DONE)]

    asyncio.run(asyncio.wait_for(check(), 3))


def test_draw_must_return_before_ownership_can_change():
    async def check():
        class ReentrantDisplay(View):
            def draw(self, image):
                with pytest.raises(RuntimeError, match="during draw"):
                    old.unbind()
                with pytest.raises(ValueError, match="occupied"):
                    host.bind(action, [B], ["display"])

        async def run():
            return DONE

        action = Callback(run)
        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(
                tasks,
                lambda *_: None,
                {"display": Resource(frozenset({"pixels"}), ReentrantDisplay())},
                pending_limit=1,
            )
            old = host.bind(action, [A], ["display"])
            old.view("display").draw(b"old")
            old.unbind()
            host.bind(action, [B], ["display"])

    asyncio.run(check())


def test_immediate_action_yields_to_ready_peer_between_calls():
    async def check():
        order = []

        async def immediate():
            return DONE

        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, lambda slot, _: order.append(slot), pending_limit=2)
            host.bind(Callback(immediate), [A])
            host.bind(Callback(immediate), [B])
            for slot in (A, A, B):
                host.dispatch(slot)
        assert order == [A, B, A]

    asyncio.run(check())


def test_listen_does_not_signal_ready_when_first_read_fails():
    from opendeck.ports import InputError
    from opendeck.source import Source

    async def check():
        source = Source[Slot]()
        source.start()
        source.fail("disconnected")
        status = []
        async with asyncio.TaskGroup() as tasks:
            host = AsyncHost(tasks, pending_limit=1)
            with pytest.raises(InputError, match="disconnected"):
                await host.listen(
                    source, source, on_ready=lambda: status.append("ready")
                )
        assert status == []

    asyncio.run(check())

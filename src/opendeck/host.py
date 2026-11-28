"""Cooperative extension host. All operations belong to the creating event loop."""

import asyncio
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from itertools import count
from threading import Lock
from typing import Literal, Protocol

from .model import Result, Slot, Status
from .ports import Input, InputError, Observer, Subject, View
from .source import Source


class AsyncAction(Protocol):
    async def run(self) -> Result: ...


class _Wake(Observer):
    def __init__(self, loop: asyncio.AbstractEventLoop, ready: asyncio.Event) -> None:
        self._loop = loop
        self._ready = ready
        self._lock = Lock()
        self._active = True

    def on_change(self) -> None:
        with self._lock:
            if self._active:
                self._loop.call_soon_threadsafe(self._ready.set)

    def deactivate(self) -> None:
        with self._lock:
            self._active = False


async def _listen[T](
    loop: asyncio.AbstractEventLoop,
    take: Callable[[], T | None],
    subject: Subject,
    deliver: Callable[[T], None],
    on_ready: Callable[[], None] | None,
) -> None:
    ready = asyncio.Event()
    wake = _Wake(loop, ready)
    try:
        subject.add(wake)
        while True:
            ready.clear()
            item = take()
            if on_ready is not None:
                on_ready()
                on_ready = None
            while item is not None:
                deliver(item)
                await asyncio.sleep(0)
                item = take()
            await ready.wait()
    finally:
        # A producer may already hold a snapshot of registered observers.
        wake.deactivate()
        subject.remove(wake)


class Subscription[T]:
    def __init__(self, share: InputShare[T], capacity: int) -> None:
        self._share = share
        self._source = Source[T](capacity)
        self._source.start()

    @property
    def input(self) -> Input[T]:
        return self._source.input

    @property
    def subject(self) -> Subject:
        return self._source.subject

    def close(self) -> None:
        self._share._check_loop()
        self._share._subscribers.discard(self)
        self._source.fail("subscription is closed")


class InputShare[T]:
    """Deliver one selected input stream to independent, bounded recipients."""

    def __init__(self, source: Input[T], subject: Subject) -> None:
        self._loop = asyncio.get_running_loop()
        self._source = source
        self._subject = subject
        self._subscribers: set[Subscription[T]] = set()
        self._closed = False
        self._listening = False

    def _check_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("use the input share on its owning event loop")

    def _check_active(self) -> None:
        self._check_loop()
        if self._closed:
            raise RuntimeError("input sharing stopped")

    def subscribe(self, *, capacity: int) -> Subscription[T]:
        self._check_active()
        subscription = Subscription(self, capacity)
        self._subscribers.add(subscription)
        return subscription

    async def listen(self, *, on_ready: Callable[[], None] | None = None) -> None:
        self._check_active()
        if self._listening:
            raise RuntimeError("input share is already listening")
        self._listening = True
        try:
            await _listen(
                self._loop, self._take, self._subject, self._deliver, on_ready
            )
        finally:
            self._stop("input sharing stopped")

    def _stop(self, error: str) -> None:
        if self._closed:
            return
        self._closed = True
        subscribers = tuple(self._subscribers)
        self._subscribers.clear()
        notifications = [
            subscription._source.record_failure(error) for subscription in subscribers
        ]
        for observers in notifications:
            Source.notify(observers)

    def _take(self) -> T | None:
        try:
            return self._source.take()
        except InputError as error:  # codex-rule-ignore: propagates source failure
            self._stop(str(error))
            raise

    def _deliver(self, item: T) -> None:
        notifications = [
            subscription._source.enqueue(item)[1]
            for subscription in tuple(self._subscribers)
        ]
        for observers in notifications:
            Source.notify(observers)


@dataclass(frozen=True, slots=True)
class Resource:
    """Adapter-defined footprint. Overlapping resources share at least one part."""

    parts: frozenset[str]
    view: View | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parts", frozenset(self.parts))
        if not self.parts:
            raise ValueError("resource needs at least one part")


@dataclass(frozen=True, slots=True)
class DispatchEvent:
    sequence: int
    slot: Slot
    phase: Literal["accepted", "rejected", "finished"]
    result: Result | None = None


class UnboundError(RuntimeError):
    pass


class _BoundView(View):
    def __init__(self, owner: Assignment, target: View) -> None:
        self._owner = owner
        self._target = target

    def draw(self, image: bytes) -> None:
        self._owner._check_active()
        self._owner._drawing += 1
        try:
            self._target.draw(image)
        finally:
            self._owner._drawing -= 1


class Assignment:
    def __init__(
        self,
        host: AsyncHost,
        action: AsyncAction,
        slots: frozenset[Slot],
        resources: dict[str, Resource],
    ) -> None:
        self._host = host
        self._action = action
        self._slots = slots
        self._resources = resources
        self._active = True
        self._drawing = 0

    def _check_active(self) -> None:
        self._host._check_loop()
        if not self._active:
            raise UnboundError("assignment is unbound")

    def view(self, name: str) -> View:
        self._check_active()
        target = self._resources[name].view
        if target is None:
            raise ValueError(f"{name} has no view")
        return _BoundView(self, target)

    def unbind(self) -> None:
        self._host._check_loop()
        if not self._active:
            return
        if self._drawing:
            raise RuntimeError("cannot unbind during draw")
        self._active = False
        for slot in self._slots:
            del self._host._slots[slot]
        for resource in self._resources.values():
            self._host._occupied.difference_update(resource.parts)


class AsyncHost:
    def __init__(
        self,
        tasks: asyncio.TaskGroup,
        report: Callable[[Slot, Result | None], None] | None = None,
        resources: Mapping[str, Resource] | None = None,
        *,
        pending_limit: int,
        trace: Callable[[DispatchEvent], None] | None = None,
    ) -> None:
        if pending_limit < 1:
            raise ValueError("pending_limit must be positive")
        self._loop = asyncio.get_running_loop()
        self._tasks = tasks
        self._report = report
        self._trace = trace
        self._sequence = count(1)
        self._limit = pending_limit
        self._resources = dict(resources or {})
        self._slots: dict[Slot, Assignment] = {}
        self._occupied: set[str] = set()
        self._queues: dict[int, deque[tuple[int, Slot, Assignment]]] = {}

    def _check_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("use the host on its owning event loop")

    def bind(
        self,
        action: AsyncAction,
        slots: Iterable[Slot],
        resources: Iterable[str] = (),
    ) -> Assignment:
        self._check_loop()
        selected = frozenset(slots)
        claimed = {name: self._resources[name] for name in resources}
        parts = {part for resource in claimed.values() for part in resource.parts}
        if selected.intersection(self._slots) or parts.intersection(self._occupied):
            raise ValueError("slot or resource already occupied")
        owner = Assignment(self, action, selected, claimed)
        self._slots.update(dict.fromkeys(selected, owner))
        self._occupied.update(parts)
        return owner

    async def listen(
        self,
        source: Input[Slot],
        subject: Subject,
        *,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        """Listen until cancelled. The caller owns the input link.

        Call on_ready after subscribing and successfully reading the logical
        input source once, even when it is empty.
        """
        self._check_loop()
        await _listen(self._loop, source.take, subject, self.dispatch, on_ready)

    def dispatch(self, slot: Slot) -> None:
        self._check_loop()
        sequence = next(self._sequence)
        owner = self._slots.get(slot)
        if owner is None:
            self._record(sequence, slot, "rejected")
            return
        key = id(owner._action)
        queue = self._queues.get(key)
        entry = (sequence, slot, owner)
        if queue is None:
            queue = deque([entry])
            self._tasks.create_task(self._run(key, queue), eager_start=False)
            self._queues[key] = queue
        elif len(queue) < self._limit:
            queue.append(entry)
        else:
            self._record(
                sequence, slot, "rejected", Result(Status.FAILED, "action queue full")
            )
            return
        self._record(sequence, slot, "accepted")

    def _record(
        self,
        sequence: int,
        slot: Slot,
        phase: Literal["accepted", "rejected", "finished"],
        result: Result | None = None,
    ) -> None:
        if self._trace is not None:
            self._trace(DispatchEvent(sequence, slot, phase, result))
        if self._report is not None and phase != "accepted":
            self._report(slot, result)

    async def _run(self, key: int, queue: deque[tuple[int, Slot, Assignment]]) -> None:
        try:
            while queue:
                sequence, slot, owner = queue[0]
                try:
                    owner._check_active()
                    result = await owner._action.run()
                except UnboundError as error:
                    result = Result(Status.FAILED, str(error))
                except asyncio.CancelledError:
                    task = asyncio.current_task()
                    if task is None or task.cancelling():
                        raise
                    result = Result(Status.UNKNOWN, "action awaitable cancelled")
                queue.popleft()
                self._record(sequence, slot, "finished", result)
                if queue:
                    await asyncio.sleep(0)
        finally:
            del self._queues[key]

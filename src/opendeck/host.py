"""Cooperative extension host. All operations belong to the creating event loop."""

import asyncio
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .model import Result, Slot, Status
from .ports import Input, Observer, Subject, View


class AsyncAction(Protocol):
    async def run(self) -> Result: ...


@dataclass(frozen=True, slots=True)
class Resource:
    """Adapter-defined footprint. Overlapping resources share at least one part."""

    parts: frozenset[str]
    view: View | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parts", frozenset(self.parts))
        if not self.parts:
            raise ValueError("resource needs at least one part")


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
        report: Callable[[Slot, Result | None], None],
        resources: Mapping[str, Resource] | None = None,
        *,
        pending_limit: int,
    ) -> None:
        if pending_limit < 1:
            raise ValueError("pending_limit must be positive")
        self._loop = asyncio.get_running_loop()
        self._tasks = tasks
        self._report = report
        self._limit = pending_limit
        self._resources = dict(resources or {})
        self._slots: dict[Slot, Assignment] = {}
        self._occupied: set[str] = set()
        self._queues: dict[int, deque[tuple[Slot, Assignment]]] = {}

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

    async def listen(self, source: Input[Slot], subject: Subject) -> None:
        """Read buffered and future input until cancelled. The caller owns the link."""
        self._check_loop()
        ready = asyncio.Event()
        loop = self._loop

        class Wake(Observer):
            def on_change(self) -> None:
                loop.call_soon_threadsafe(ready.set)

        wake = Wake()
        try:
            subject.add(wake)
            while True:
                ready.clear()
                while (slot := source.take()) is not None:
                    self.dispatch(slot)
                    await asyncio.sleep(0)
                await ready.wait()
        finally:
            subject.remove(wake)

    def dispatch(self, slot: Slot) -> None:
        self._check_loop()
        owner = self._slots.get(slot)
        if owner is None:
            self._report(slot, None)
            return
        key = id(owner._action)
        queue = self._queues.get(key)
        if queue is None:
            queue = deque([(slot, owner)])
            self._tasks.create_task(self._run(key, queue), eager_start=False)
            self._queues[key] = queue
        elif len(queue) < self._limit:
            queue.append((slot, owner))
        else:
            self._report(slot, Result(Status.FAILED, "action queue full"))

    async def _run(self, key: int, queue: deque[tuple[Slot, Assignment]]) -> None:
        try:
            while queue:
                slot, owner = queue[0]
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
                self._report(slot, result)
                if queue:
                    await asyncio.sleep(0)
        finally:
            del self._queues[key]

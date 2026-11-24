import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

from .domain import AgentEvent
from .repository import Repository
from .tenancy import DEFAULT_WORKSPACE_ID


class RunStream:
    def __init__(self, repository: Repository):
        self.repository = repository
        self._subscribers: dict[str, set[asyncio.Queue[AgentEvent]]] = defaultdict(set)

    async def publish(self, event: AgentEvent) -> None:
        for queue in tuple(self._subscribers[event.run_id]):
            await queue.put(event)

    async def stream(
        self,
        run_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> AsyncIterator[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        subscribers = self._subscribers[run_id]
        subscribers.add(queue)
        seen: set[int] = set()
        try:
            for event in self.repository.list_events(run_id):
                seen.add(event.sequence)
                yield event

            run = self.repository.get_run(run_id, workspace_id)
            if run is None:
                return
            if run.status in {"completed", "partial", "failed"}:
                return

            while True:
                event = await queue.get()
                if event.sequence not in seen:
                    seen.add(event.sequence)
                    yield event
                if event.phase == "run" and event.status in {
                    "completed",
                    "partial",
                    "failed",
                }:
                    return
        finally:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(run_id, None)

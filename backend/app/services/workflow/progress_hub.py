import asyncio
import uuid
from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache
from typing import Dict, Iterator, Set

from app.core.config import PROGRESS_QUEUE_SIZE
from app.schemas.job import JobStatusResponseSchema


# Hand each job update to the WebSocket connections watching its project.
# Source: MS2 FR02 – Outputs (real-time progress notifications to the UI); architecture §1 (WebSockets).
class JobProgressHub:
    """Used only from the API's event loop. Each connection keeps just the newest update, so a slow client
    delays nobody and, when it catches up, jumps to the current state."""

    def __init__(self) -> None:
        self._watchers: Dict[uuid.UUID, Set[asyncio.Queue]] = defaultdict(set)

    @contextmanager
    def watch(self, project_id: uuid.UUID) -> Iterator[asyncio.Queue]:
        updates: asyncio.Queue = asyncio.Queue(maxsize=PROGRESS_QUEUE_SIZE)
        self._watchers[project_id].add(updates)
        try:
            yield updates
        finally:
            self._watchers[project_id].discard(updates)
            if not self._watchers[project_id]:
                del self._watchers[project_id]

    def publish(self, update: JobStatusResponseSchema) -> None:
        for updates in self._watchers.get(update.project_id, ()):
            if updates.full():
                updates.get_nowait()
            updates.put_nowait(update)


@lru_cache
def get_progress_hub() -> JobProgressHub:
    """One hub per API process, shared by the event consumer, the sweep and the WebSocket endpoint."""
    return JobProgressHub()

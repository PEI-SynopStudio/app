import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, sessionmaker

from app.api.errors import SERVICE_ERRORS
from app.core.config import (
    ASGI_WEBSOCKET_DISCONNECT,
    INGESTION_ROUTE_TAG,
    PROGRESS_WS_ROUTE,
    PROJECTS_ROUTE_PREFIX,
    WS_CLOSE_PROJECT_NOT_FOUND,
)
from app.database.session import get_session_factory
from app.schemas.job import JobStatusResponseSchema
from app.services.projects.projects import get_project
from app.services.workflow.jobs import latest_ingestion_job
from app.services.workflow.progress_hub import JobProgressHub, get_progress_hub

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[INGESTION_ROUTE_TAG])


# Send the current state of the project's ingestion job, then every change while the client stays connected.
# Source: MS2 FR02 – Outputs (real-time progress notifications to the UI); architecture §1 (WebSockets).
@router.websocket(PROGRESS_WS_ROUTE)
async def watch_progress(
    websocket: WebSocket,
    project_id: str,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    hub: JobProgressHub = Depends(get_progress_hub),
):
    """Accepted before checking the project, because a browser cannot read why a handshake was refused."""
    await websocket.accept()
    try:
        # Watching starts before the state is read, so an update in between is not missed.
        with hub.watch(uuid.UUID(project_id)) as updates:
            current = await asyncio.to_thread(_latest_state, session_factory, project_id)
            if current is not None:
                await websocket.send_text(current.model_dump_json())
            await _stream(websocket, updates)
    except SERVICE_ERRORS:
        await websocket.close(code=WS_CLOSE_PROJECT_NOT_FOUND)
    except WebSocketDisconnect:
        pass


def _latest_state(session_factory: sessionmaker[Session], project_id: str) -> Optional[JobStatusResponseSchema]:
    """A short session: a connection can stay open for hours and must not hold a database connection."""
    with session_factory() as db:
        job = latest_ingestion_job(db, get_project(db, project_id).id)
        return JobStatusResponseSchema.model_validate(job) if job is not None else None


async def _stream(websocket: WebSocket, updates: asyncio.Queue) -> None:
    """Send each update until the client disconnects; anything the client sends is ignored."""

    async def send_updates() -> None:
        while True:
            update = await updates.get()
            await websocket.send_text(update.model_dump_json())

    sender = asyncio.create_task(send_updates())
    try:
        while (await websocket.receive())["type"] != ASGI_WEBSOCKET_DISCONNECT:
            pass
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)

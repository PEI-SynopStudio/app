import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import owns
from app.api.errors import SERVICE_ERRORS
from app.core.config import (
    ASGI_WEBSOCKET_DISCONNECT,
    JOBS_ROUTE_TAG,
    PROGRESS_WS_ROUTE,
    ERROR_PROJECT_NOT_FOUND,
    PROJECTS_ROUTE_PREFIX,
    SESSION_COOKIE_NAME,
    WS_CLOSE_NOT_AUTHENTICATED,
    WS_CLOSE_PROJECT_NOT_FOUND,
)
from app.database.session import get_session_factory
from app.schemas.job import JobStatusResponseSchema
from app.services.auth.auth import resolve_session
from app.services.projects.projects import ProjectNotFoundError, get_project
from app.services.workflow.jobs import latest_ingestion_job, latest_project_job
from app.services.workflow.progress_hub import JobProgressHub, get_progress_hub

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[JOBS_ROUTE_TAG])


class NotAuthenticatedError(Exception):
    pass


# Send the current state of the project's ingestion job, then every change while the client stays connected.
# Only the project's owner may watch; the browser sends the session cookie with the handshake.
@router.websocket(PROGRESS_WS_ROUTE)
async def watch_progress(
    websocket: WebSocket,
    project_id: str,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    hub: JobProgressHub = Depends(get_progress_hub),
):
    """Accepted before checking the project, because a browser cannot read why a handshake was refused."""
    await websocket.accept()
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    try:
        # Watching starts before the state is read, so an update in between is not missed.
        with hub.watch(uuid.UUID(project_id)) as updates:
            current = await asyncio.to_thread(_latest_state, session_factory, token, project_id)
            if current is not None:
                await websocket.send_text(current.model_dump_json())
            await _stream(websocket, updates)
    except NotAuthenticatedError:
        await websocket.close(code=WS_CLOSE_NOT_AUTHENTICATED)
    except SERVICE_ERRORS:
        await websocket.close(code=WS_CLOSE_PROJECT_NOT_FOUND)
    except WebSocketDisconnect:
        pass


def _latest_state(
    session_factory: sessionmaker[Session], token: Optional[str], project_id: str
) -> Optional[JobStatusResponseSchema]:
    """A short session: a connection can stay open for hours and must not hold a database connection.

    The session is checked once, when the connection opens; signing out does not close a connection already open.
    """
    with session_factory() as db:
        session = resolve_session(db, token)
        if session is None:
            raise NotAuthenticatedError()
        project = get_project(db, project_id)
        if not owns(session.user, project):
            raise ProjectNotFoundError(ERROR_PROJECT_NOT_FOUND.format(project_id=project_id))
        job = latest_ingestion_job(db, project.id)
        job = latest_project_job(db, get_project(db, project_id).id)
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

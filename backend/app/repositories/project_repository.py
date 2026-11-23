"""
Project repository - projects storage.

Prototype!!! Only depends of the interface. Dont need to change for db afterwards.
"""

from threading import Lock
from typing import Protocol

from app.schemas.project import Project, ProjectStatus


class ProjectRepository(Protocol):
    def add(self, project: Project) -> Project: ...
    def get(self, project_id: str) -> Project | None: ...
    def list_by_owner(
        self,
        owner_id: str,
        *,
        status: ProjectStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Project], int]: ...
    def update(self, project: Project) -> Project: ...
    def delete(self, project_id: str) -> bool: ...


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._lock = Lock()

    def add(self, project: Project) -> Project:
        with self._lock:
            self._projects[project.id] = project
        return project

    def get(self, project_id: str) -> Project | None:
        with self._lock:
            return self._projects.get(project_id)

    def list_by_owner(
        self,
        owner_id: str,
        *,
        status: ProjectStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Project], int]:
        with self._lock:
            items = [p for p in self._projects.values() if p.owner_id == owner_id]

        if status is not None:
            items = [p for p in items if p.status == status]
        if query:
            q = query.casefold()
            items = [
                p for p in items
                if q in p.title.casefold()
                or (p.description and q in p.description.casefold())
            ]

        items.sort(key=lambda p: p.updated_at, reverse=True)
        return items[offset : offset + limit], len(items)

    def update(self, project: Project) -> Project:
        with self._lock:
            self._projects[project.id] = project
        return project

    def delete(self, project_id: str) -> bool:
        with self._lock:
            return self._projects.pop(project_id, None) is not None
"""
Project service - projects and library business rules.
"""

from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.project_repository import (
    InMemoryProjectRepository,
    ProjectRepository,
)
from app.schemas.project import (
    Project,
    ProjectCreate,
    ProjectLibrary,
    ProjectStatus,
    ProjectUpdate,
)


class ProjectNotFoundError(Exception):
    pass


class ProjectService:
    def __init__(self, repo: ProjectRepository):
        self.repo = repo

    def create(self, owner_id: str, data: ProjectCreate) -> Project:
        now = datetime.now(timezone.utc)
        project = Project(
            id=str(uuid4()),
            owner_id=owner_id,
            title=data.title,
            description=data.description,
            created_at=now,
            updated_at=now,
        )
        return self.repo.add(project)

    def get_for_owner(self, owner_id: str, project_id: str) -> Project:
        project = self.repo.get(project_id)
        if project is None or project.owner_id != owner_id:
            raise ProjectNotFoundError(project_id)
        return project

    def library(
        self,
        owner_id: str,
        *,
        status: ProjectStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectLibrary:
        items, total = self.repo.list_by_owner(
            owner_id, status=status, query=query, limit=limit, offset=offset
        )
        return ProjectLibrary(items=items, total=total)

    def update(self, owner_id: str, project_id: str, data: ProjectUpdate) -> Project:
        project = self.get_for_owner(owner_id, project_id)
        # title/status null are ignored; description null clears the field.
        changes = {
            k: v
            for k, v in data.model_dump(exclude_unset=True).items()
            if v is not None or k == "description"
        }
        if not changes:
            return project
        changes["updated_at"] = datetime.now(timezone.utc)
        return self.repo.update(project.model_copy(update=changes))

    def delete(self, owner_id: str, project_id: str) -> None:
        self.get_for_owner(owner_id, project_id)
        self.repo.delete(project_id)


_repository = InMemoryProjectRepository()


def get_project_service() -> ProjectService:
    return ProjectService(_repository)
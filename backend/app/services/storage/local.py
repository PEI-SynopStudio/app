import uuid
from pathlib import Path

from app.core.config import ERROR_INVALID_PROJECT_ID, PROJECTS_DIR, get_settings


class LocalStorage:
    """Per-project file storage on the local media volume.

    Layout: <root>/projects/<project_id>/{source,audio,proxy,uploads}/. Kept small so it can be
    swapped for an S3-compatible backend (SeaweedFS) later.
    """

    def __init__(self, root: Path):
        self.root = root

    def project_dir(self, project_id: str) -> Path:
        # Project IDs must be UUIDs; this also prevents path traversal through the ID.
        try:
            normalized = str(uuid.UUID(project_id))
        except (ValueError, AttributeError, TypeError):
            raise ValueError(ERROR_INVALID_PROJECT_ID.format(project_id=project_id))
        return self.root / PROJECTS_DIR / normalized

    def path(self, project_id: str, *parts: str) -> Path:
        """Return a path inside the project directory, creating its parent directories."""
        target = self.project_dir(project_id).joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target


def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().media_root)

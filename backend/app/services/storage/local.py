import shutil
import uuid
from pathlib import Path

from app.core.config import ERROR_INVALID_PROJECT_ID, PROJECTS_DIR, UPLOADS_DIR, WORKING_DIRS, get_settings


class LocalStorage:
    """Per-project working area on the local media volume: files being processed and chunks being uploaded.

    Layout: <root>/projects/<project_id>/{source,audio,proxy,analysis,uploads}/. PyAV and yt-dlp need local
    files; what must last is kept in object storage (ObjectStorage).
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

    def delete(self, project_id: str, key: str) -> None:
        """Remove a file of the project if it exists; `key` is relative to the project directory."""
        (self.project_dir(project_id) / key).unlink(missing_ok=True)

    def delete_working_files(self, project_id: str) -> None:
        """Remove what a job left behind; the chunks of uploads still in progress stay."""
        for directory in WORKING_DIRS:
            shutil.rmtree(self.project_dir(project_id) / directory, ignore_errors=True)

    def delete_upload(self, project_id: str, upload_id: str) -> None:
        """Remove the chunks of an upload that was never completed."""
        shutil.rmtree(self.project_dir(project_id) / UPLOADS_DIR / upload_id, ignore_errors=True)

    def delete_project(self, project_id: str) -> None:
        """Remove every file of the project (US34)."""
        shutil.rmtree(self.project_dir(project_id), ignore_errors=True)


def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().media_root)

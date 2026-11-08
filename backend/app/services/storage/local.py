import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import (
    ERROR_INVALID_PROJECT_ID,
    JSON_ENCODING,
    JSON_INDENT,
    PROJECTS_DIR,
    TMP_SUFFIX,
    get_settings,
)


class LocalStorage:
    """Per-project file storage on the local media volume.

    Layout: <root>/projects/<project_id>/{source,audio,proxy,analysis}/ plus JSON documents
    (project.json, ingestion.json, metadata.json). Kept small so it can be swapped for an
    S3-compatible backend (SeaweedFS) later.
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

    def write_json(self, project_id: str, name: str, data: Dict[str, Any]) -> Path:
        """Write a JSON document atomically (temp file + rename) so readers never see a partial file."""
        target = self.path(project_id, name)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=TMP_SUFFIX)
        try:
            with os.fdopen(fd, "w", encoding=JSON_ENCODING) as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=JSON_INDENT)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return target

    def delete(self, project_id: str, name: str) -> None:
        """Remove a file of the project if it exists."""
        (self.project_dir(project_id) / name).unlink(missing_ok=True)

    def read_json(self, project_id: str, name: str) -> Optional[Dict[str, Any]]:
        target = self.project_dir(project_id) / name
        if not target.exists():
            return None
        return json.loads(target.read_text(encoding=JSON_ENCODING))


def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().media_root)

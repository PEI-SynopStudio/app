"""Stand-ins for SeaweedFS in API tests: objects kept in a dictionary, or a storage that always fails."""
from app.services.storage.object_storage import ObjectStorage, ObjectStorageError


class InMemoryObjectStorage(ObjectStorage):
    def __init__(self):
        self.objects = {}

    def put_file(self, project_id, key, path):
        self.objects[(project_id, key)] = path.read_bytes()

    def delete(self, project_id, key):
        self.objects.pop((project_id, key), None)

    def delete_project(self, project_id):
        self.objects = {item: data for item, data in self.objects.items() if item[0] != project_id}

    def signed_url(self, project_id, key, content_type, expires_in_seconds):
        return f"https://storage.test/{project_id}/{key}?type={content_type}&expires={expires_in_seconds}"


class UnavailableObjectStorage(ObjectStorage):
    def put_file(self, project_id, key, path):
        raise ObjectStorageError("storage down")

    def delete(self, project_id, key):
        raise ObjectStorageError("storage down")

    def delete_project(self, project_id):
        raise ObjectStorageError("storage down")

    def signed_url(self, project_id, key, content_type, expires_in_seconds):
        raise ObjectStorageError("storage down")

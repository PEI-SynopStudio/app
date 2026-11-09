"""Stand-ins for SeaweedFS in API tests: objects kept in a dictionary, or a storage that always fails."""
import uuid

from app.services.storage.object_storage import ObjectStorage, ObjectStorageError


class InMemoryObjectStorage(ObjectStorage):
    def __init__(self):
        self.objects = {}
        self.open_uploads = {}

    def put_file(self, project_id, key, path):
        self.objects[(project_id, key)] = path.read_bytes()

    def delete(self, project_id, key):
        self.objects.pop((project_id, key), None)

    def delete_project(self, project_id):
        self.objects = {item: data for item, data in self.objects.items() if item[0] != project_id}
        self.open_uploads = {item: data for item, data in self.open_uploads.items() if item[0] != project_id}

    def get_file(self, project_id, key, path):
        if (project_id, key) not in self.objects:
            raise ObjectStorageError("no such object")
        path.write_bytes(self.objects[(project_id, key)])

    def start_chunked_upload(self, project_id, key):
        upload_id = uuid.uuid4().hex
        self.open_uploads[(project_id, key, upload_id)] = {}
        return upload_id

    def put_chunk(self, project_id, key, upload_id, index, data):
        self.open_uploads[(project_id, key, upload_id)][index] = data.read()

    def received_chunks(self, project_id, key, upload_id):
        return set(self.open_uploads[(project_id, key, upload_id)])

    def complete_chunked_upload(self, project_id, key, upload_id):
        chunks = self.open_uploads.pop((project_id, key, upload_id))
        self.objects[(project_id, key)] = b"".join(chunks[index] for index in sorted(chunks))

    def abort_chunked_upload(self, project_id, key, upload_id):
        self.open_uploads.pop((project_id, key, upload_id), None)

    def signed_url(self, project_id, key, content_type, expires_in_seconds):
        return f"https://storage.test/{project_id}/{key}?type={content_type}&expires={expires_in_seconds}"


class UnavailableObjectStorage(ObjectStorage):
    def put_file(self, project_id, key, path):
        raise ObjectStorageError("storage down")

    def delete(self, project_id, key):
        raise ObjectStorageError("storage down")

    def delete_project(self, project_id):
        raise ObjectStorageError("storage down")

    def get_file(self, project_id, key, path):
        raise ObjectStorageError("storage down")

    def start_chunked_upload(self, project_id, key):
        raise ObjectStorageError("storage down")

    def put_chunk(self, project_id, key, upload_id, index, data):
        raise ObjectStorageError("storage down")

    def received_chunks(self, project_id, key, upload_id):
        raise ObjectStorageError("storage down")

    def complete_chunked_upload(self, project_id, key, upload_id):
        raise ObjectStorageError("storage down")

    def abort_chunked_upload(self, project_id, key, upload_id):
        raise ObjectStorageError("storage down")

    def signed_url(self, project_id, key, content_type, expires_in_seconds):
        raise ObjectStorageError("storage down")

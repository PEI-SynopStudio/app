from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import DOCUMENT_ROUTE, DOCUMENTS_ROUTE, DOCUMENTS_ROUTE_TAG, PROJECTS_ROUTE_PREFIX
from app.database.session import get_db
from app.schemas.document import DocumentResponse
from app.services.projects.documents import add_document, delete_document, list_documents
from app.services.storage.object_storage import ObjectStorage, get_object_storage

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[DOCUMENTS_ROUTE_TAG])

# TODO(auth): pass the user's ID as owner_id, as in app/api/projects.py.


@router.get(DOCUMENTS_ROUTE, response_model=List[DocumentResponse])
def read_documents(project_id: str, db: Session = Depends(get_db)):
    try:
        return [DocumentResponse.model_validate(document) for document in list_documents(db, project_id)]
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Receive one supporting document as multipart form data (field "file"); send one request per file.
# Source: MS2 FR03, US08.
@router.post(DOCUMENTS_ROUTE, status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
def upload(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    object_storage: ObjectStorage = Depends(get_object_storage),
):
    try:
        document = add_document(db, object_storage, project_id, file.filename, file.content_type, file.file)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
    return DocumentResponse.model_validate(document)


@router.delete(DOCUMENT_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def delete(
    project_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    object_storage: ObjectStorage = Depends(get_object_storage),
):
    try:
        delete_document(db, object_storage, project_id, document_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
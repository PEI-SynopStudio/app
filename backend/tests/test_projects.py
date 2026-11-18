import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.project_repository import InMemoryProjectRepository
from app.services.projects.project_service import ProjectService, get_project_service

ALICE = {"X-User-Id": "alice"}
BOB = {"X-User-Id": "bob"}


@pytest.fixture
def client():
    service = ProjectService(InMemoryProjectRepository())
    app.dependency_overrides[get_project_service] = lambda: service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_created_project_appears_in_library(client):
    r = client.post("/projects", json={"title": "Aula 1"}, headers=ALICE)
    assert r.status_code == 201
    assert r.json()["status"] == "draft"

    library = client.get("/projects", headers=ALICE).json()
    assert library["total"] == 1
    assert library["items"][0]["title"] == "Aula 1"


def test_library_is_per_user(client):
    pid = client.post("/projects", json={"title": "Aula 1"}, headers=ALICE).json()["id"]
    assert client.get("/projects", headers=BOB).json()["total"] == 0
    assert client.get(f"/projects/{pid}", headers=BOB).status_code == 404


def test_requires_user_header(client):
    assert client.get("/projects").status_code == 401


def test_rejects_blank_title(client):
    r = client.post("/projects", json={"title": "   "}, headers=ALICE)
    assert r.status_code == 422


def test_update_archive_and_delete(client):
    pid = client.post("/projects", json={"title": "Aula 1"}, headers=ALICE).json()["id"]

    r = client.patch(f"/projects/{pid}", json={"status": "archived"}, headers=ALICE)
    assert r.json()["status"] == "archived"
    assert client.get("/projects?status=draft", headers=ALICE).json()["total"] == 0

    assert client.delete(f"/projects/{pid}", headers=ALICE).status_code == 204
    assert client.get(f"/projects/{pid}", headers=ALICE).status_code == 404
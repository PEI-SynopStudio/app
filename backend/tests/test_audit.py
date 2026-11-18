import uuid
from datetime import date

from sqlalchemy import select

from app.core.config import AuditAction, LicenseType
from app.database.models import AuditLog
from app.schemas.project import ProjectCreate
from app.services.audit.audit import record_audit
from app.services.projects.projects import create_project


def project_data(licence=True):
    return ProjectCreate(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=licence,
        authorship_confirmed=True,
    )


def audit_details(db, project_id):
    query = select(AuditLog).where(AuditLog.project_id == project_id)
    return {entry.action: entry.details for entry in db.scalars(query)}


def test_a_new_project_records_its_creation_and_licence(db):
    project = create_project(db, project_data())

    assert audit_details(db, project.id) == {
        AuditAction.PROJECT_CREATED: {"title": "Debate"},
        AuditAction.LICENCE_CONFIRMED: {
            "author": "University of Aveiro",
            "license_type": "creative_commons",
            "copyright_notice": "CC BY 4.0",
            "licence_confirmed": True,
            "authorship_confirmed": True,
        },
    }


def test_an_unconfirmed_licence_is_not_recorded_as_confirmed(db):
    project = create_project(db, project_data(licence=False))

    assert list(audit_details(db, project.id)) == [AuditAction.PROJECT_CREATED]


def test_an_audit_entry_is_only_saved_with_the_change_it_records(db):
    project_id = uuid.uuid4()
    record_audit(db, project_id, AuditAction.PROJECT_CREATED)

    db.rollback()

    assert audit_details(db, project_id) == {}

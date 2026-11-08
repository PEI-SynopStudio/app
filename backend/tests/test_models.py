from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import LicenseType, MediaAssetStatus, ProjectStatus, SourceType
from app.database.models import AudioTrack, MediaAsset, Project


def make_project():
    return Project(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana", "Rui"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=True,
        authorship_confirmed=True,
    )


def make_asset(project):
    return MediaAsset(
        project=project, source_type=SourceType.UPLOAD, file_name="debate.mp4", status=MediaAssetStatus.PROCESSING
    )


def make_track(asset):
    return AudioTrack(media_asset=asset, sample_rate=16000, channels=1, format="wav", storage_key="audio/audio.wav")


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_project_keeps_the_fr01_metadata(db):
    project = make_project()
    db.add(project)
    db.commit()
    db.expire_all()

    stored = db.get(Project, project.id)
    assert stored.speakers == ["Ana", "Rui"]
    assert stored.recording_date == date(2026, 10, 1)
    assert stored.status == ProjectStatus.DRAFT
    assert stored.owner_id is None


def test_enums_are_stored_by_value(db):
    db.add(make_project())
    db.commit()

    row = db.execute(text("SELECT status, license_type FROM projects")).one()
    assert tuple(row) == ("draft", "creative_commons")


def test_timestamps_are_timezone_aware(db):
    project = make_project()
    db.add(project)
    db.commit()
    db.expire_all()

    assert db.get(Project, project.id).created_at.tzinfo is not None


def test_a_media_asset_has_only_one_audio_track(db):
    asset = make_asset(make_project())
    db.add(make_track(asset))
    db.commit()

    db.add(AudioTrack(media_asset_id=asset.id, sample_rate=16000, channels=1, format="wav", storage_key="other.wav"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_a_project_removes_its_media(db):
    project = make_project()
    db.add(make_track(make_asset(project)))
    db.commit()
    db.expire_all()

    db.delete(project)
    db.commit()

    assert (count(db, Project), count(db, MediaAsset), count(db, AudioTrack)) == (0, 0, 0)

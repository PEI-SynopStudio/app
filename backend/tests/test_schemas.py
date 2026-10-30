from uuid import uuid4
import pytest
from pydantic import ValidationError

from app.schemas.enums import JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum, JobTypeEnum
from app.schemas.job import (
    IngestionParams,
    JobParametersSchema,
    JobUpdateEventSchema,
    TranscriptionParams,
    JobRequestMessage,
    JobCreateSchema
)
from app.schemas.timecode import parse_time

URL = "https://youtu.be/SdfR7TuJdlc?si=zvxHtwpH2raXzsau"



# =====================================================================
# 1. TIMECODE
# =====================================================================
def test_parsetime_valid():
    assert parse_time("01:30") == 90
    assert parse_time("02:00") == 120
    assert parse_time("01:00:00") == 3600

def test_parsetime_invalid():
    with pytest.raises(ValueError):
        parse_time("X")
    with pytest.raises(ValueError):
        parse_time("01:71")


# =====================================================================
# 2. INGESTION
# =====================================================================
def test_ingestion_withonlyonesources():
    with pytest.raises(ValueError):
        IngestionParams(source_url=URL, media_id=uuid4())
    with pytest.raises(ValueError):
        IngestionParams()
        
    assert IngestionParams(source_url=URL).media_id is None
    assert IngestionParams(media_id=uuid4()).source_url is None


def test_ingestion_rejectnonhttp():
    with pytest.raises(ValueError):
        IngestionParams(source_url="/etc/video.mp4")

def test_ingestion_interval():
    with pytest.raises(ValueError):
        IngestionParams(source_url=URL, time_start="02:00", time_end="01:00")
    
    with pytest.raises(ValueError):
        IngestionParams(source_url=URL, time_start="01:00", time_end="01:00")
        
    with pytest.raises(ValueError):
        IngestionParams(source_url=URL, time_start="X", time_end="01:00")
    IngestionParams(source_url=URL, time_start="00:51", time_end="01:45")
    IngestionParams(source_url=URL, time_start="00:51")
    IngestionParams(source_url=URL, time_end="01:45")
    
        
    
# =====================================================================
# 3. TRANSCRIPTION
# =====================================================================
def test_transcription_rejectparamsfromclient():
    with pytest.raises(ValueError):
        TranscriptionParams(media_id=uuid4(), language="portuguese")
        
    with pytest.raises(ValueError):
        TranscriptionParams(media_id=uuid4(), whisper_model="x")
        
    assert TranscriptionParams(media_id=uuid4()).language == "pt"
    

# =====================================================================
# 4. EVENTS
# =====================================================================
def _event(**kw):
    base = dict(job_id=uuid4(), step=JobStepProcessingEnum.DOWNLOADING_MEDIA, step_progress=10, status=JobStatusEnum.PROCESSING)
    return JobUpdateEventSchema(**{**base, **kw})


def test_event_failed():
    with pytest.raises(ValidationError):
        _event(status=JobStatusEnum.FAILED)
    
    assert _event(status=JobStatusEnum.FAILED, error_code=JobErrorCodeEnum.NO_AUDIO_TRACK).error_code is JobErrorCodeEnum.NO_AUDIO_TRACK
    with pytest.raises(ValidationError):
        _event(error_code=JobErrorCodeEnum.CORRUPTED_MEDIA)
        

def test_event_progress():
    with pytest.raises(ValidationError):
        _event(step_progress=110)
    
    assert _event().step_progress<=100
    

# =====================================================================
# 5. FLOW BETWEEN BROKER <-> WORKER
# =====================================================================
def test_requestmessage_json():
    msg = JobRequestMessage(job_id=uuid4(), project_id=uuid4(), parameters=IngestionParams(source_url=URL))
    msg2 = JobRequestMessage.model_validate_json(msg.model_dump_json())
    
    assert msg == msg2
    assert msg2.parameters.job_type == "ingestion"
    
def test_requestmessage_rightparams():
    raw = {
            "job_id": str(uuid4()),
            "project_id": str(uuid4()),
            "parameters": {"job_type": "transcription", "media_id": str(uuid4())},
        }
    assert isinstance(JobRequestMessage.model_validate(raw).parameters, TranscriptionParams)

def test_updatemessage_validation():
    with pytest.raises(ValidationError):
        JobUpdateEventSchema(job_id=uuid4(),attempt=1,step=JobStepProcessingEnum.TRANSCRIBING,step_progress=50.0,status=JobStatusEnum.FAILED,error_code=None)

    with pytest.raises(ValidationError):
        JobUpdateEventSchema(job_id=uuid4(),attempt=1,step=JobStepProcessingEnum.FINISHED,step_progress=100.0,status=JobStatusEnum.COMPLETED,error_code=JobErrorCodeEnum.NO_AUDIO_TRACK)


    with pytest.raises(ValidationError):
        JobUpdateEventSchema(job_id=uuid4(),attempt=1,step=JobStepProcessingEnum.DOWNLOADING_MEDIA,step_progress=20.0,status=JobStatusEnum.PROCESSING,error_code=JobErrorCodeEnum.INVALID_SOURCE)


    valid_event = JobUpdateEventSchema(job_id=uuid4(), attempt=1, step=JobStepProcessingEnum.DOWNLOADING_MEDIA,step_progress=45.5,status=JobStatusEnum.PROCESSING)
    assert valid_event.status == JobStatusEnum.PROCESSING
    assert valid_event.step_progress == 45.5
    
# =====================================================================
# 6. MODES
# =====================================================================
def test_picksrightmode():
    job = JobCreateSchema.model_validate(
            {"parameters": {"job_type": "ingestion", "source_url": URL}}
        )
    assert isinstance(job.parameters, IngestionParams)
    assert job.job_type is JobTypeEnum.INGESTION
    
    with pytest.raises(ValidationError):
        JobCreateSchema.model_validate({"parameters": {"job_type": "nope"}})

def test_matchenum():
    for params in (IngestionParams, TranscriptionParams):
        literal = params.model_fields["job_type"].default
        assert literal in {t.value for t in JobTypeEnum}
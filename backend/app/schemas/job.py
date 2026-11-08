from __future__ import annotations
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.core.config import get_settings
from app.schemas.enums import AcousticProfileEnum, JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum, JobTypeEnum
from app.schemas.timecode import parse_time



# =====================================
# CONTRATOS DE DADOS E ESQUEMAS PYDANTIC
# =====================================

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
 
 
class _StrictModel(BaseModel):
    # extra="forbid": campos desconhecidos (ex.: um "video_path" enviado pelo
    # cliente) dão 422 em vez de serem ignorados em silêncio.
    model_config = ConfigDict(extra="forbid")


# =====================================================================
# 1. PARÂMETROS POR TIPO DE JOB.
# =====================================================================

class IngestionParams(_StrictModel):
    job_type: Literal["ingestion"] = "ingestion"
    source_url: HttpUrl | None = None
    media_id: UUID | None = None   # referência a um upload
    time_start: str | None = None
    time_end: str | None = None
    
    @model_validator(mode="after")
    def _validate(self) -> IngestionParams:
        if (self.source_url is None) == (self.media_id is None):
            raise ValueError("Indique exatamente um de source url ou media id")
        start = parse_time(self.time_start) if self.time_start is not None else None
        end = parse_time(self.time_end) if self.time_end is not None else None
        
        if start is not None and end is not None and end <= start:
            raise ValueError("time_end tem de ser posterior a time_start")
        return self
    
"""
class JobParametersSchema(BaseModel):
    # Fontes de vídeo
    video_url: str | None = None
    video_path: str | None = None
    
    # Intervalos de corte
    time_start: str | None = None
    time_end: str | None = None
    
    # Visão computacional
    reference_image_path: str | None = None
    similarity_threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    min_face_confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    padding_seconds: float = Field(default=10.0, ge=0.0)
    merge_gap_seconds: float = Field(default=60.0, ge=0.0)
    resize_scale: float = Field(default=0.5, gt=0.0, le=1.0)
    scan_every_seconds: float = Field(default=1.0, gt=0.0)
    
    # Transcrição de áudio
    whisper_model: str = settings.WHISPER_MODEL
    language: str = settings.DEFAULT_LANGUAGE
    
    @model_validator(mode="after")
    def validate_source_and_intervals(self) -> JobParametersSchema:
        if not self.video_url and not self.video_path:
            raise ValueError("Tem de fornecer pelo menos o url ou o path")
        
        if self.time_start is not None and self.time_end is not None:
            t_start = parse_time(self.time_start)
            t_end = parse_time(self.time_end)
            if t_end <= t_start: raise ValueError("O final tem de ser superior ao inicio")
        
        return self
"""

class TranscriptionParams(_StrictModel):
    """
    O modelo (whisper, etc.) NÃO é escolhido pelo cliente: é configuração do worker.
    """
    
    job_type: Literal["transcription"] = "transcription"
    media_id: UUID
    language: str = Field(default=get_settings().default_language, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    acoustic_profile: AcousticProfileEnum | None = None

JobParameters = Annotated[IngestionParams | TranscriptionParams,Field(discriminator="job_type")]

class JobCreateSchema(_StrictModel):
    """Corpo do POST /projects/{project_id}/jobs.
 
    O project_id vem do caminho do URL e o tipo vem de parameters.job_type:
    assim não há duas fontes de verdade que possam discordar.
    """
    parameters: JobParameters
    
    @property
    def job_type(self) -> JobTypeEnum:
        return JobTypeEnum(self.parameters.job_type)
    


# =====================================================================
# 2. EVENTO DO WORKER (broker)
# =====================================================================
class JobRequestMessage(BaseModel):
    """API -> worker. Publicada no exchange 'jobs' com routing key = job_type."""
    
    job_id: UUID
    project_id: UUID
    attempt: int = Field(default=1, ge=1)
    parameters: JobParameters
    requested_at: datetime = Field(default_factory=_utcnow) 
    


class JobUpdateEventSchema(BaseModel):
    """Worker -> API. Progresso, conclusão ou falha."""
    job_id: UUID
    event_id: UUID = Field(default_factory=uuid4)
    attempt: int = Field(default=1, ge=1)
    step: JobStepProcessingEnum | None = None
    step_progress: float = Field(ge=0.0, le=100.0)
    status: JobStatusEnum
    error_code: JobErrorCodeEnum | None = None
    error_message: str | None = None
    output: dict[str, Any] | None = None
    emitted_at: datetime = Field(default_factory=_utcnow)
    
    @model_validator(mode="after")
    def _validate(self) -> JobUpdateEventSchema:
        if self.status == JobStatusEnum.FAILED and self.error_code is None:
            raise ValueError("error_code é obrigatório quando status=failed")
        
        if self.status != JobStatusEnum.FAILED and self.error_code is not None:
            raise ValueError("error_code só é permitido quando status=failed")
        
        return self
    

# =====================================================================
# 3. RESPOSTA DA API
# =====================================================================
class JobStatusResponseSchema(BaseModel):
    job_id: UUID
    project_id: UUID
    job_type: JobTypeEnum
    status: JobStatusEnum
    step: JobStepProcessingEnum | None = None
    step_progress: float = Field(default=0.0, ge=0.0, le=100.0)
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    attempt: int = Field(default=1, ge=1)
    error_code: JobErrorCodeEnum | None = None
    error_message: str | None = None
    output: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    

    model_config = ConfigDict(from_attributes=True)




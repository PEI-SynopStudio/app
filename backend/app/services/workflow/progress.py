from __future__ import annotations

from app.schemas.enums import JobStatusEnum, JobStepProcessingEnum, JobTypeEnum
from app.core.exceptions import InvalidStepError    

MAX_PROGRESS = 99.0

def getstepweight(job_type: JobTypeEnum, step: JobStepProcessingEnum) -> tuple[float, float]:
    match (job_type, step):
        # --- INGESTION ---
        case (JobTypeEnum.INGESTION, JobStepProcessingEnum.INITIALIZING):
            return (0.0, 5.0)
        case (JobTypeEnum.INGESTION, JobStepProcessingEnum.DOWNLOADING_MEDIA):
            return (5.0, 45.0)
        case (JobTypeEnum.INGESTION, JobStepProcessingEnum.INSPECTING_MEDIA):
            return (45.0, 50.0)
        case (JobTypeEnum.INGESTION, JobStepProcessingEnum.EXTRACTING_AUDIO):
            return (50.0, 70.0)
        case (JobTypeEnum.INGESTION, JobStepProcessingEnum.GENERATING_PROXY):
            return (70.0, 90.0)
        case (JobTypeEnum.INGESTION, JobStepProcessingEnum.PERSISTING_RESULTS):
            return (90.0, 95.0)
        case (JobTypeEnum.INGESTION, JobStepProcessingEnum.CLEANING_UP):
            return (95.0, 100.0)
        case (JobTypeEnum.INGESTION, JobStepProcessingEnum.FINISHED):
            return (100.0, 100.0)

        # --- TRANSCRIPTION ---
        case (JobTypeEnum.TRANSCRIPTION, JobStepProcessingEnum.INITIALIZING):
            return (0.0, 5.0)
        case (JobTypeEnum.TRANSCRIPTION, JobStepProcessingEnum.TRANSCRIBING):
            return (5.0, 65.0)
        case (JobTypeEnum.TRANSCRIPTION, JobStepProcessingEnum.DIARIZING):
            return (65.0, 90.0)
        case (JobTypeEnum.TRANSCRIPTION, JobStepProcessingEnum.PERSISTING_RESULTS):
            return (90.0, 95.0)
        case (JobTypeEnum.TRANSCRIPTION, JobStepProcessingEnum.CLEANING_UP):
            return (95.0, 100.0)
        case (JobTypeEnum.TRANSCRIPTION, JobStepProcessingEnum.FINISHED):
            return (100.0, 100.0)
        
        case _:
            raise InvalidStepError(job_type.value, step.value)
        
def calculateprogress(job_type: JobTypeEnum, step: JobStepProcessingEnum | None, status: JobStatusEnum, step_progress:float) -> float:
    if status == JobStatusEnum.COMPLETED:
        return 100.0
    
    if step is None:
        return 0.0
    
    startw, endw = getstepweight(job_type, step)
    clampedstep = max(0.0, min(100.0, step_progress)) # força o valor entre 0.0 e 100.0
    progress = startw + (clampedstep / 100.0)*(endw - startw) # calcula o ponto global
    return min(round(progress, 2), MAX_PROGRESS)
    
import logging
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Dict

from app.core.config import (
    ALIGNMENT_PAD_SECONDS,
    AUDIO_FILE,
    ERROR_AUDIO_KEY_MISSING,
    ERROR_STORAGE_UNAVAILABLE,
    ERROR_TRANSCRIPTION_INTERNAL,
    JSON_DUMP_MODE,
    LOG_TRANSCRIPTION_FAILED,
    PARAMETER_ALIGNMENT_PAD_SECONDS,
    PARAMETER_CUT_PAUSE_SECONDS,
    PARAMETER_CUT_SEARCH_SECONDS,
    PARAMETER_MAX_IDENTICAL_SEGMENTS,
    PARAMETER_WINDOW_SECONDS,
    PROGRESS_MAX,
    PROGRESS_MIN,
    SPEECH_DIR,
    TRANSCRIPT_DIR,
    TRANSCRIPT_FILE,
    TRANSCRIPTION_CUT_PAUSE_SECONDS,
    TRANSCRIPTION_CUT_SEARCH_SECONDS,
    TRANSCRIPTION_WINDOW_SECONDS,
    WHISPER_MAX_IDENTICAL_SEGMENTS,
    JobErrorCodeEnum,
    JobStatusEnum,
    JobStepProcessingEnum,
)
from app.core.exceptions import MediaRejectedError
from app.schemas.job import JobRequestMessage, JobUpdateEventSchema
from app.schemas.transcript import TranscriptDocument, TranscriptionOutput
from app.services.speech.alignment import align_segment
from app.services.speech.assembly import build_document, build_segment
from app.services.speech.audio import audio_duration_seconds, iter_audio_windows
from app.services.speech.models import LoadedAligner, LoadedWhisper
from app.services.speech.transcription import transcribe_window, whisper_parameters
from app.services.storage.local import LocalStorage
from app.services.storage.object_storage import ObjectStorage, ObjectStorageError
from app.services.video.ingestion import ProgressCallback
from app.services.workflow.ingestion_pipeline import EventEmitter, _throttled

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeechModels:

    whisper: LoadedWhisper
    aligner: Callable[[str], LoadedAligner]


def run_transcription(
    storage: LocalStorage,
    object_storage: ObjectStorage,
    models: SpeechModels,
    request: JobRequestMessage,
    emit: EventEmitter,
) -> JobUpdateEventSchema:
    project_id = str(request.project_id)
    scratch = (SPEECH_DIR, str(request.job_id))
    language = request.parameters.language

    def publish(**fields) -> JobUpdateEventSchema:
        event = JobUpdateEventSchema(job_id=request.job_id, attempt=request.attempt, **fields)
        emit(event)
        return event

    def advance(step: JobStepProcessingEnum) -> ProgressCallback:
        publish(status=JobStatusEnum.PROCESSING, step=step, step_progress=PROGRESS_MIN)
        return _throttled(lambda percent: publish(status=JobStatusEnum.PROCESSING, step=step, step_progress=percent))

    def fail(code: JobErrorCodeEnum, message: str) -> JobUpdateEventSchema:
        storage.delete_dir(project_id, *scratch)
        return publish(status=JobStatusEnum.FAILED, step_progress=PROGRESS_MIN, error_code=code, error_message=message)

    try:
        advance(JobStepProcessingEnum.INITIALIZING)
        if not request.audio_key:
            raise ValueError(ERROR_AUDIO_KEY_MISSING)
        aligner = models.aligner(language)
        wav_path = storage.path(project_id, *scratch, AUDIO_FILE)
        object_storage.get_file(project_id, request.audio_key, wav_path)

        report = advance(JobStepProcessingEnum.TRANSCRIBING)
        duration = audio_duration_seconds(wav_path)
        segments = []
        for window in iter_audio_windows(wav_path):
            offset = request.time_offset_seconds + window.start_seconds
            for segment in transcribe_window(models.whisper.model, window.samples, language):
                segments.append(build_segment(segment, align_segment(aligner, window.samples, segment), offset))
                report(PROGRESS_MAX * (window.start_seconds + segment.end) / duration)
        document = build_document(language, segments)

        advance(JobStepProcessingEnum.PERSISTING_RESULTS)
        key = PurePosixPath(TRANSCRIPT_DIR, TRANSCRIPT_FILE).as_posix()
        document_path = storage.path(project_id, *scratch, TRANSCRIPT_FILE)
        document_path.write_text(document.model_dump_json())
        object_storage.put_file(project_id, key, document_path)
        output = _build_output(models, aligner, request, document, key)

        advance(JobStepProcessingEnum.CLEANING_UP)
    except MediaRejectedError as exc:
        return fail(exc.code, str(exc))
    except (ValueError, FileNotFoundError) as exc:
        return fail(JobErrorCodeEnum.INVALID_SOURCE, str(exc))
    except RuntimeError as exc:
        return fail(JobErrorCodeEnum.MODEL_UNAVAILABLE, str(exc))
    except ObjectStorageError:
        logger.exception(LOG_TRANSCRIPTION_FAILED, project_id)
        return fail(JobErrorCodeEnum.INTERNAL_ERROR, ERROR_STORAGE_UNAVAILABLE)
    except Exception:
        logger.exception(LOG_TRANSCRIPTION_FAILED, project_id)
        fail(JobErrorCodeEnum.INTERNAL_ERROR, ERROR_TRANSCRIPTION_INTERNAL)
        raise

    storage.delete_dir(project_id, *scratch)
    return publish(status=JobStatusEnum.COMPLETED, step_progress=PROGRESS_MAX, output=output.model_dump(mode=JSON_DUMP_MODE))


def transcription_parameters() -> Dict[str, Any]:
    return {
        **whisper_parameters(),
        PARAMETER_WINDOW_SECONDS: TRANSCRIPTION_WINDOW_SECONDS,
        PARAMETER_CUT_SEARCH_SECONDS: TRANSCRIPTION_CUT_SEARCH_SECONDS,
        PARAMETER_CUT_PAUSE_SECONDS: TRANSCRIPTION_CUT_PAUSE_SECONDS,
        PARAMETER_MAX_IDENTICAL_SEGMENTS: WHISPER_MAX_IDENTICAL_SEGMENTS,
        PARAMETER_ALIGNMENT_PAD_SECONDS: ALIGNMENT_PAD_SECONDS,
    }


def _build_output(
    models: SpeechModels, aligner: LoadedAligner, request: JobRequestMessage, document: TranscriptDocument, key: str
) -> TranscriptionOutput:
    words = [word for segment in document.segments for word in segment.words]
    return TranscriptionOutput(
        transcript_key=key,
        language=document.language,
        model_name=models.whisper.name,
        model_revision=models.whisper.revision,
        alignment_model_name=aligner.name,
        alignment_model_revision=aligner.revision,
        parameters=transcription_parameters(),
        time_offset_seconds=request.time_offset_seconds,
        segment_count=len(document.segments),
        word_count=len(words),
        aligned_word_count=sum(word.aligned for word in words),
    )

import asyncio
import logging

from app.core.config import LOG_FORMAT, JobTypeEnum, get_settings
from app.schemas.job import JobRequestMessage
from app.services.speech.models import load_aligner, load_whisper
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import ObjectStorage, get_object_storage
from app.services.workflow.transcription_pipeline import SpeechModels, run_transcription
from app.workers.job_worker import JobWorker


class SpeechWorker(JobWorker):
    job_type = JobTypeEnum.TRANSCRIPTION

    def __init__(self, url: str, storage: LocalStorage, object_storage: ObjectStorage, models: SpeechModels) -> None:
        super().__init__(url)
        self._storage = storage
        self._object_storage = object_storage
        self._models = models

    def run_job(self, request: JobRequestMessage) -> None:
        run_transcription(self._storage, self._object_storage, self._models, request, self._emit)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    settings = get_settings()
    whisper = load_whisper()
    load_aligner(settings.default_language)
    models = SpeechModels(whisper, load_aligner)
    asyncio.run(SpeechWorker(settings.rabbitmq_url, get_storage(), get_object_storage(), models).run())


if __name__ == "__main__":
    main()

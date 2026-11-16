from typing import Literal


import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import torch
from faster_whisper import WhisperModel, download_model
from huggingface_hub import snapshot_download
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

from app.core.config import (
    ALIGNMENT_MODEL_FILES,
    ALIGNMENT_MODELS,
    ERROR_NO_ALIGNMENT_MODEL,
    ERROR_SPEECH_MODEL_UNAVAILABLE,
    LANGUAGE_SUBTAG_SEPARATOR,
    LOG_SPEECH_MODEL_LOADED,
    get_settings,
)

logger = logging.getLogger(__name__)

_LOAD_ERRORS = (OSError, RuntimeError, ValueError)


@dataclass(frozen=True)
class LoadedWhisper:
    name: str
    revision: str
    model: WhisperModel


@dataclass(frozen=True)
class LoadedAligner:
    name: str
    revision: str
    model: Wav2Vec2ForCTC
    processor: Wav2Vec2Processor


@lru_cache(maxsize=None)
def load_whisper() -> LoadedWhisper:
    settings = get_settings()
    try:
        path = Path(download_model(settings.whisper_model, cache_dir=str(settings.speech_models_dir)))
        model = WhisperModel(
            str(path),
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            cpu_threads=settings.speech_cpu_threads,
        )
    except _LOAD_ERRORS as exc:
        raise RuntimeError(ERROR_SPEECH_MODEL_UNAVAILABLE.format(model=settings.whisper_model, details=exc)) from exc
    logger.info(LOG_SPEECH_MODEL_LOADED, settings.whisper_model, path.name)
    return LoadedWhisper(settings.whisper_model, path.name, model)


def load_aligner(language: str) -> LoadedAligner:
    name = ALIGNMENT_MODELS.get(language.split(LANGUAGE_SUBTAG_SEPARATOR)[0])
    if name is None:
        raise RuntimeError(ERROR_NO_ALIGNMENT_MODEL.format(language=language))
    return _load_alignment_model(name)


@lru_cache(maxsize=None)
def _load_alignment_model(name: str) -> LoadedAligner:
    settings = get_settings()
    try:
        path = Path(
            snapshot_download(
                name, cache_dir=str(settings.speech_models_dir), allow_patterns=list[Literal['*.json', '*.safetensors', 'pytorch_model.bin']](ALIGNMENT_MODEL_FILES)
            )
        )
        processor = Wav2Vec2Processor.from_pretrained(str(path))
        model = Wav2Vec2ForCTC.from_pretrained(str(path)).to(settings.whisper_device)
    except _LOAD_ERRORS as exc:
        raise RuntimeError(ERROR_SPEECH_MODEL_UNAVAILABLE.format(model=name, details=exc)) from exc
    model.eval()
    # torch keeps one thread pool per process, used by every later alignment.
    torch.set_num_threads(settings.speech_cpu_threads)
    logger.info(LOG_SPEECH_MODEL_LOADED, name, path.name)
    return LoadedAligner(name, path.name, model, processor)

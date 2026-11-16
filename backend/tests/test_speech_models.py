from typing import Literal


import pytest
from faster_whisper import download_model
from huggingface_hub import snapshot_download

from app.core.config import ALIGNMENT_MODEL_FILES, ALIGNMENT_MODELS, get_settings
from app.services.speech import models
from app.services.speech.models import load_aligner, load_whisper

COMMIT_HASH_LENGTH = 40


@pytest.fixture(autouse=True)
def fresh_models():
    load_whisper.cache_clear()
    models._load_alignment_model.cache_clear()
    yield
    load_whisper.cache_clear()
    models._load_alignment_model.cache_clear()


def _fail_download(*args, **kwargs):
    raise OSError("network unreachable")


def _cached(download) -> bool:
    try:
        download()
    except (OSError, ValueError):
        return False
    return True


def _whisper_cached() -> bool:
    settings = get_settings()
    return _cached(
        lambda: download_model(
            settings.whisper_model, cache_dir=str(settings.speech_models_dir), local_files_only=True
        )
    )


def _aligner_cached() -> bool:
    return _cached(
        lambda: snapshot_download(
            ALIGNMENT_MODELS["pt"],
            cache_dir=str(get_settings().speech_models_dir),
            allow_patterns=list[Literal['*.json', '*.safetensors', 'pytorch_model.bin']](ALIGNMENT_MODEL_FILES),
            local_files_only=True,
        )
    )


def test_language_without_alignment_model_is_rejected():
    with pytest.raises(RuntimeError, match="'xx'"):
        load_aligner("xx")


def test_whisper_load_error_becomes_runtime_error(monkeypatch):
    monkeypatch.setattr(models, "download_model", _fail_download)

    with pytest.raises(RuntimeError, match="network unreachable"):
        load_whisper()


def test_aligner_load_error_becomes_runtime_error(monkeypatch):
    monkeypatch.setattr(models, "snapshot_download", _fail_download)

    with pytest.raises(RuntimeError, match="network unreachable"):
        load_aligner("pt-PT")


@pytest.mark.skipif(not _whisper_cached(), reason="the faster-whisper weights are not in SPEECH_MODELS_DIR")
def test_whisper_loads_once_with_its_revision():
    loaded = load_whisper()

    assert loaded is load_whisper()
    assert len(loaded.revision) == COMMIT_HASH_LENGTH


@pytest.mark.skipif(not _aligner_cached(), reason="the wav2vec2 weights are not in SPEECH_MODELS_DIR")
def test_aligner_loads_once_in_inference_mode():
    loaded = load_aligner("pt")

    assert loaded is load_aligner("pt-PT")
    assert not loaded.model.training
    assert "a" in loaded.processor.tokenizer.get_vocab()
    assert len(loaded.revision) == COMMIT_HASH_LENGTH

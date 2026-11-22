from statistics import fmean
from typing import Sequence

from app.core.config import ERROR_NO_SPEECH_DETECTED, TRANSCRIPT_TIME_DECIMALS, JobErrorCodeEnum
from app.core.exceptions import MediaRejectedError
from app.schemas.transcript import TranscriptDocument, TranscriptSegment, TranscriptWord
from app.services.speech.alignment import AlignedWord
from app.services.speech.transcription import WhisperSegment


def build_segment(segment: WhisperSegment, words: Sequence[AlignedWord], offset_seconds: float) -> TranscriptSegment:
    transcript_words = [
        TranscriptWord(
            text=word.text,
            start=_in_recording(word.start, offset_seconds),
            end=_in_recording(word.end, offset_seconds),
            confidence=word.probability,
            aligned=word.aligned,
        )
        for word in words
    ]
    return TranscriptSegment(
        text=segment.text,
        start=min(word.start for word in transcript_words),
        end=max(word.end for word in transcript_words),
        confidence=fmean(word.confidence for word in transcript_words),
        avg_logprob=segment.avg_logprob,
        no_speech_prob=segment.no_speech_prob,
        compression_ratio=segment.compression_ratio,
        temperature=segment.temperature,
        words=transcript_words,
    )


def build_document(language: str, segments: Sequence[TranscriptSegment]) -> TranscriptDocument:
    if not segments:
        raise MediaRejectedError(JobErrorCodeEnum.NO_SPEECH_DETECTED, ERROR_NO_SPEECH_DETECTED)
    return TranscriptDocument(language=language, segments=list(segments))


def _in_recording(seconds: float, offset_seconds: float) -> float:
    return round(offset_seconds + seconds, TRANSCRIPT_TIME_DECIMALS)

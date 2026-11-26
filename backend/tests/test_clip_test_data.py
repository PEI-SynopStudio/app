from pathlib import Path

from app.schemas.transcript import TranscriptDocument

SHORT_TRANSCRIPT = Path(__file__).parent / "data" / "clips" / "short_transcript.json"


def test_short_transcript_is_a_valid_transcript_document():
    document = TranscriptDocument.model_validate_json(SHORT_TRANSCRIPT.read_bytes())

    words = [word for segment in document.segments for word in segment.words]
    assert document.language == "pt"
    assert all(previous.end <= word.start for previous, word in zip(words, words[1:]))

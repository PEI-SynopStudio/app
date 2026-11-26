from __future__ import annotations

import uuid
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import (
    CHAPTER_SUMMARY_MAX_LENGTH,
    CHAPTER_TITLE_MAX_LENGTH,
    CLIP_AUDIENCE_MAX_LENGTH,
    CLIP_DEFAULT_MAX_SECONDS,
    CLIP_DEFAULT_MIN_SECONDS,
    CLIP_MAX_RANGES,
    CLIP_MAX_SECONDS,
    CLIP_MIN_SECONDS,
    CLIP_RATIONALE_MAX_LENGTH,
    CLIP_TITLE_MAX_LENGTH,
    CLIP_TOPIC_MAX_LENGTH,
    ERROR_CLIP_DURATION_ORDER,
    ERROR_RANGE_ORDER,
    FIRST_POSITION,
    RATING_MAX,
    RATING_MIN,
    SCORE_MAX,
    SCORE_MIN,
    AspectRatioEnum,
    ClipWarningEnum,
    DiscardReasonEnum,
    ScoreCriterionEnum,
)
from app.schemas.transcript import Count, Seconds

Position = Annotated[int, Field(ge=FIRST_POSITION)]
Rating = Annotated[int, Field(ge=RATING_MIN, le=RATING_MAX)]
Score = Annotated[float, Field(ge=SCORE_MIN, le=SCORE_MAX)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Transcript units ---
class Sentence(BaseModel):
    index: Position
    first_word: Position
    last_word: Position
    start: Seconds
    end: Seconds
    speaker: Optional[str] = None
    text: str


class SentenceRange(BaseModel):
    """Inclusive range of sentence numbers."""

    first: Position
    last: Position

    @model_validator(mode="after")
    def _validate(self) -> SentenceRange:
        if self.last < self.first:
            raise ValueError(ERROR_RANGE_ORDER.format(first=self.first, last=self.last))
        return self


# --- User options (FR09) ---
class ClipOptions(_StrictModel):
    """Body of POST /projects/{project_id}/clips; also stored with each clip."""

    min_duration_seconds: int = Field(default=CLIP_DEFAULT_MIN_SECONDS, ge=CLIP_MIN_SECONDS, le=CLIP_MAX_SECONDS)
    max_duration_seconds: int = Field(default=CLIP_DEFAULT_MAX_SECONDS, ge=CLIP_MIN_SECONDS, le=CLIP_MAX_SECONDS)
    topic: Optional[str] = Field(default=None, max_length=CLIP_TOPIC_MAX_LENGTH)
    audience: Optional[str] = Field(default=None, max_length=CLIP_AUDIENCE_MAX_LENGTH)
    aspect_ratio: AspectRatioEnum = AspectRatioEnum.PORTRAIT

    @model_validator(mode="after")
    def _validate(self) -> ClipOptions:
        if self.max_duration_seconds < self.min_duration_seconds:
            raise ValueError(ERROR_CLIP_DURATION_ORDER)
        return self


# --- LLM replies: the JSON each prompt must return (validated by LLMClient) ---
# Unknown fields are ignored: models often add some, and they carry nothing we use.
class TopicDraft(BaseModel):
    first_sentence: Position
    last_sentence: Position
    title: str = Field(min_length=1, max_length=CHAPTER_TITLE_MAX_LENGTH)
    summary: str = Field(min_length=1, max_length=CHAPTER_SUMMARY_MAX_LENGTH)


class TopicReply(BaseModel):
    topics: List[TopicDraft] = Field(min_length=1)


class CandidateDraft(BaseModel):
    ranges: List[SentenceRange] = Field(min_length=1, max_length=CLIP_MAX_RANGES)
    title: str = Field(min_length=1, max_length=CLIP_TITLE_MAX_LENGTH)
    rationale: str = Field(min_length=1, max_length=CLIP_RATIONALE_MAX_LENGTH)


class CandidateReply(BaseModel):
    candidates: List[CandidateDraft]  # empty when the topic has no good excerpt


class RatingDraft(BaseModel):
    clip: Position  # number of the clip in the list sent to the model
    scores: Dict[ScoreCriterionEnum, Rating]


class RatingReply(BaseModel):
    ratings: List[RatingDraft]


# --- Pipeline values ---
class Topic(BaseModel):
    position: Position
    first_sentence: Position
    last_sentence: Position
    first_word: Position
    last_word: Position
    start: Seconds
    end: Seconds
    title: str
    summary: str


class ClipCandidate(BaseModel):
    topic_position: Position
    ranges: List[SentenceRange]
    title: str
    rationale: str


class SourceInterval(BaseModel):
    """One continuous part of the original recording. A clip plays its intervals in list order."""

    first_sentence: Position
    last_sentence: Position
    first_word: Position
    last_word: Position
    start: Seconds
    end: Seconds


class ClipRating(BaseModel):
    clip_position: Position
    scores: Dict[ScoreCriterionEnum, Rating]


class ClipProposal(BaseModel):
    position: Position  # order shown to the user: by score, or by time in the video
    topic_position: Position
    title: str
    rationale: str
    intervals: List[SourceInterval] = Field(min_length=1)
    duration_seconds: Seconds
    warnings: List[ClipWarningEnum] = Field(default_factory=list)
    score: Optional[Score] = None
    score_breakdown: Optional[Dict[ScoreCriterionEnum, Rating]] = None


class DiscardedCandidate(BaseModel):
    topic_position: Position
    ranges: List[SentenceRange]
    reason: DiscardReasonEnum


class ValidationResult(BaseModel):
    clips: List[ClipProposal]
    discarded: List[DiscardedCandidate]


class LLMInfo(BaseModel):
    provider: str
    model: str


# --- Worker output ---
class ClipProposalDocument(BaseModel):
    """Stored in object storage at clips/{job_id}/proposals.json."""

    ai_generated: Literal[True] = True
    transcript_id: uuid.UUID
    options: ClipOptions
    llm: LLMInfo
    prompt_versions: Dict[str, str]
    topics: List[Topic]
    clips: List[ClipProposal]
    discarded: List[DiscardedCandidate]


class ClipProposalOutput(BaseModel):
    """The output of the completed job event, kept in jobs.output."""

    proposals_key: str
    transcript_id: uuid.UUID
    topic_count: Count
    candidate_count: Count
    clip_count: Count
    discarded_count: Dict[DiscardReasonEnum, Count]
    llm: LLMInfo
    prompt_versions: Dict[str, str]
    llm_call_count: Count
    llm_seconds: Seconds

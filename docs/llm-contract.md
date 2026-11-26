# SynopStudio – LLM and Clip Generation Contract

> Scope: Milestone 4 tasks T4.11 (LLM layer), T4.12 (topic segmentation), T4.13 (clip candidates), T4.14 (validation and traceability), T4.15 (scoring and ranking, Extra), T4.16 (clip proposal job). It also fixes what T4.17–T4.20, T4.23 and T4.27 build on.
> Owners: David and Murilo. Consumers: Daniel (proposals page, T4.18), Lucas (clip settings and approval, T4.17, T4.20), Tomás (validation reuse in the editor, T4.19).
> Requirement IDs refer to `docs/requirements.md`; components and workers to `docs/architecture.md`; code rules to `AGENTS.md`.
> Change control: after this contract is merged, any change to it goes in its own pull request approved by both owners. Code that disagrees with this document is a bug in the code or in the document, never a silent decision.

## How to read the code in this document

The contract is not the implementation of any task. It fixes the shapes the two owners share, so both can work at the same time against the same definitions. Every code block carries one of these labels:

| Label | Meaning | Where the code is written |
| --- | --- | --- |
| **[Contract PR]** | Final code, with no logic: data formats, abstract interfaces, errors, enums, the fake provider. Both owners import it from day 1. | The contract pull request, exactly as shown |
| **[Signature]** | Only the public names, parameters, return types and documented behaviour are fixed. The body is not part of the contract. | The branch of the task named in the label |
| **[Fixed format]** | The content is fixed by the contract, but the file is created by the task that first needs it. | The branch of the task named in the label |

Changing anything labelled **[Contract PR]** or **[Fixed format]**, or the signature of anything labelled **[Signature]**, needs a contract pull request approved by both owners.

## 1. Rules this contract guarantees

These come from `AGENTS.md` and `docs/requirements.md`. Every section below is built so that they hold.

| Rule | How this contract enforces it | Source |
| --- | --- | --- |
| The LLM never writes quotes and never invents times | The LLM sees numbered sentences and answers only with sentence numbers, titles and rationales. Times are computed in code from the word timestamps. Quoted text in a title or rationale must exist in the clip's transcript (section 9, rule 6). | FR11, FR15, NFR "zero fabricated quotes" |
| Every clip has a verifiable link to its source | Each clip stores its exact source intervals (word positions, sentence numbers and seconds) and the job keeps a snapshot of the transcript the AI saw (section 11.3). | FR11, NFR ±100 ms |
| No processing without licence and authorship | `POST /projects/{id}/clips` refuses (403) before any job exists. | FR01 |
| Long work is asynchronous | The endpoint answers 202 and publishes a job to RabbitMQ; a worker runs the pipeline. | AGENTS.md |
| Workers never touch PostgreSQL | The clip worker reads the transcript snapshot from object storage and reports results as job events; the API persists them. | architecture section 2 |
| Every AI recommendation and every user change is audited | Topics, each proposed clip (with its rationale) and each approval or rejection are written to the audit log. | FR18, NFR "rationale for 100% of AI decisions" |
| AI-generated text is labelled, machine-readably | Topics and clips carry `ai_generated: true` plus the provider, model and prompt versions. | FR16, MS3 1.3.1 |
| Nothing is rendered without human approval | Clips start as `proposed`; only `approved` clips can be rendered or exported (T4.20, T4.21). | FR15 |
| LLM providers are swappable through configuration only | One interface, two implementations, chosen by environment variables plus `app/core/llm.toml`. | NFR Maintainability (≥ 2 providers) |
| No hardcoded values | Every name, limit, message and default listed in section 15 lives in `backend/app/core/config.py`; prompt texts live in files. | AGENTS.md |
| Personal data stays in our infrastructure | Transcripts are only sent to self-hosted models (Ollama, or an OpenAI-compatible server we run). Prompt and response texts are not logged unless `LLM_LOG_CONTENT=true`. | MS3 1.1 (GDPR) |

## 2. End-to-end flow

```
Browser ── POST /projects/{id}/clips (ClipOptions) ──► API                                  [Murilo]
   │                                                    ├─ checks: owner, licence, transcript ready, no active clip job
   │                                                    ├─ writes the transcript snapshot to object storage
   │                                                    ├─ creates the job, audit "clip_proposal.requested"
   │◄── 202 JobStatusResponseSchema ────────────────────┴─ publishes JobRequestMessage to jobs.clip_proposal
   │
   │   clip-worker (ClipWorker, JobWorker subclass)                                             [Murilo]
   │     └─ run_clip_proposal(...)                                                              [David]
   │          1. initializing        snapshot → build_sentences()                               [Murilo]
   │          2. segmenting_topics   segment_topics()        ── LLM: topic_segmentation         [Murilo]
   │          3. proposing_clips     propose_candidates() ×N ── LLM: clip_candidates            [Murilo]
   │          4. validating_clips    validate_candidates()   (no LLM)                           [David]
   │          5. ranking_clips       rate_clips() + rank_clips() (only if ranking is enabled)   [Murilo + David]
   │          6. persisting_results  ClipProposalDocument → object storage
   │          7. cleaning_up → completed, output = ClipProposalOutput
   │
   ├── WS /projects/{id}/progress (step and progress of every event, as for ingestion)
   │
   API event consumer → record_clip_proposal_outcome()                                          [Murilo]
        ├─ stores topics and clips (status "proposed")
        └─ audit "topics.generated", one "clip.proposed" per clip, "clip_proposal.completed"

Browser ── GET /projects/{id}/clips ── PATCH /projects/{id}/clips/{clip_id} {"status": "approved"} ──► audit
```

## 3. Division of work and file ownership

The split follows the clip generation plan: David builds the LLM layer, the validation and the pipeline that chains the steps; Murilo builds the sentences, the prompts and the LLM steps that use them, and the job structure around the pipeline (database, worker, API). The Jira owner of T4.11 must be updated to David.

Each person edits only their own files. `config.py` is the only shared file, and each person writes only in their section (section 15). Only Murilo creates Alembic migrations.

| Area | File | Owner | Task |
| --- | --- | --- | --- |
| Contract | `docs/llm-contract.md` | David (Murilo reviews) | contract |
| Data formats | `backend/app/schemas/clips.py` | contract PR; changes need both | contract |
| Job parameters | `backend/app/schemas/job.py` (new `ClipProposalParams`, `transcript_key`) | contract PR | contract |
| Shared enums and constants | `backend/app/core/config.py`, "Clip generation – shared" section | contract PR | contract |
| LLM interface | `backend/app/services/llm/provider.py`, `backend/app/services/llm/errors.py` | contract PR (David) | contract |
| API formats | `backend/app/schemas/clip_api.py` | Murilo | T4.16a |
| LLM client, retries, call log | `backend/app/services/llm/client.py` | David | T4.11 |
| Prompt loading | `backend/app/services/llm/prompts.py` | David | T4.11 |
| Providers | `backend/app/services/llm/ollama.py`, `backend/app/services/llm/openai_compatible.py`, `backend/app/services/llm/factory.py` | David | T4.11 |
| Provider profiles | `backend/app/core/llm.toml` | David | T4.11 |
| Validation | `backend/app/services/clips/validation.py` | David | T4.14 |
| Ranking formula | `backend/app/services/clips/ranking.py` | David | T4.15 |
| Pipeline | `backend/app/services/workflow/clip_proposal_pipeline.py` | David | T4.16b |
| Sentences | `backend/app/services/clips/sentences.py` | Murilo | base of T4.12–T4.14 |
| Topics | `backend/app/services/clips/topics.py` | Murilo | T4.12 |
| Candidates | `backend/app/services/clips/candidates.py` | Murilo | T4.13 |
| Rating step | `backend/app/services/clips/rating.py` | Murilo | T4.15 |
| Prompt texts | `backend/app/prompts/*.txt` | Murilo | T4.12, T4.13, T4.15 |
| Worker | `backend/app/workers/clip_worker.py`, `clip-worker` and `ollama` services in `docker-compose.yml` | Murilo | T4.16a |
| Database | `backend/app/database/models/topic.py`, `clip.py`, `models/__init__.py`, `backend/migrations/versions/0010_topics_and_clips.py` | Murilo | T4.16a |
| Submission and results | `backend/app/services/workflow/submission.py` (`submit_clip_proposal`), `backend/app/services/workflow/clip_proposal_results.py`, the hook in `event_consumer.py` | Murilo | T4.16a |
| Clip service and API | `backend/app/services/clips/clips.py`, `backend/app/api/clips.py`, router in `main.py`, mappings in `api/errors.py` | Murilo | T4.16a |
| Fake provider | `backend/tests/fake_llm_provider.py` | contract PR (David) | contract |
| Synthetic test transcript | `backend/tests/data/clips/short_transcript.json` | contract PR (David) | contract |
| Real test transcript | `backend/tests/data/clips/lecture_transcript.json` | Murilo | contract |
| Tests | `test_llm_*.py`, `test_clip_validation.py`, `test_clip_ranking.py`, `test_clip_proposal_pipeline.py` | David | — |
| Tests | `test_clip_sentences.py`, `test_clip_topics.py`, `test_clip_candidates.py`, `test_clip_rating.py`, `test_clip_worker.py`, `test_clip_proposal_results.py`, `test_api_clips.py` | Murilo | — |

`backend/Dockerfile` only copies `app/`, `alembic.ini` and `migrations/`, so the prompts and `llm.toml` live under `app/` and need no Dockerfile change.

## 4. Naming

- **Sentence**: the unit the LLM sees and answers with (section 5).
- **Topic**: a contiguous block of sentences about one subject. The domain model calls it `Topic` and the table is `topics`; the interface may show it as "chapter". Code always says topic.
- **Candidate**: what the LLM proposes for one topic, before validation.
- **Clip**: a validated candidate with exact source intervals. Stored in the `clips` table with a review status.
- Positions and numbers are **0-based** everywhere: sentence `index`, word positions (equal to `transcript_words.position`), topic `position`, clip `position`.
- Times are **seconds in the original recording** as `float` with 3 decimals (`TRANSCRIPT_TIME_DECIMALS`), the same unit as `TranscriptWord.start` and `end`. Never milliseconds.

## 5. Sentences

### 5.1 Definition

A sentence is built from the transcript **words**, in order, across the whole transcript. Whisper segment boundaries are ignored: they are acoustic windows, and a segment can hold half a sentence or several sentences.

A word's **position** is its index in the flattened word list of the `TranscriptDocument` (segments in order, words in order). This is the same number as `TranscriptWord.position` in the database.

A sentence ends after a word when the first of these holds:

1. The word ends with a character in `SENTENCE_END_CHARACTERS` (`.`, `?`, `!`, `…`), and the word, lowercased, is not in `SENTENCE_ABBREVIATIONS` (for example `sr.`, `sra.`, `dr.`, `dra.`, `prof.`, `profª.`, `p.ex.`).
2. The pause before the next word is at least `SENTENCE_MAX_PAUSE_SECONDS` (2.0 s).
3. The sentence has reached `SENTENCE_MAX_WORDS` (60) words or `SENTENCE_MAX_SECONDS` (20 s). This keeps unpunctuated speech from becoming one huge sentence that no clip duration can hold.
4. The next word has a different speaker (only after diarization, T4.8).

The last word of the transcript always ends a sentence. Sentences are numbered from 0 in order.

| Field | Value |
| --- | --- |
| `index` | 0, 1, 2, ... |
| `first_word`, `last_word` | positions of the first and last word (inclusive) |
| `start` | `start` of the first word |
| `end` | `end` of the last word |
| `speaker` | speaker label of the words, or `null` until diarization exists |
| `text` | the words' `text` joined with one space (faster-whisper words are already stripped) |

Sentences are **not stored**. They are recomputed from the transcript with `build_sentences`, which is deterministic: the same transcript always gives the same sentences. Clips store word positions as well as sentence numbers, so they stay valid if the sentence rules change later.

### 5.2 Prompt format

One line per sentence:

```
[42] (12:03, 4s) Speaker 1: Inflation in 2024 was lower than expected.
[43] (12:07, 3s) Speaker 1: This is mainly due to three factors.
```

- `[index]`, then the start time and the rounded duration in parentheses, then the speaker and a colon, then the text.
- Start time is `MM:SS` below one hour and `H:MM:SS` from one hour (`PROMPT_TIMECODE_FORMAT`, `PROMPT_TIMECODE_FORMAT_HOURS`), rounded down to the second.
- The duration helps the model respect the requested clip length; it is rounded to whole seconds, at least 1.
- Without diarization the speaker and its colon are left out: `[42] (12:03, 4s) Inflation in 2024 ...`.
- `format_sentences(sentences)` produces exactly this text, one sentence per line, joined with `\n`.

## 6. Data formats

### 6.1 Pipeline formats (`backend/app/schemas/clips.py`)

**[Contract PR]** The single source of the types the two owners exchange. Constant names are defined in section 15.

```python
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
```

### 6.2 API formats (`backend/app/schemas/clip_api.py`)

**[Fixed format]** Written in T4.16a (Murilo). Kept apart from `clips.py` because `ClipListResponse` embeds `JobStatusResponseSchema`, and `schemas/job.py` already imports `ClipOptions` from `clips.py`; one file importing both avoids a circular import. Daniel and Lucas build their pages on these shapes.

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.core.config import ClipStatusEnum, ClipWarningEnum, ScoreCriterionEnum
from app.schemas.clips import ClipOptions, Position, Rating, Score, SourceInterval, _StrictModel
from app.schemas.job import JobStatusResponseSchema
from app.schemas.transcript import Seconds


class ClipStatusUpdate(_StrictModel):
    """Body of PATCH /projects/{project_id}/clips/{clip_id} (T4.20)."""

    status: Literal[ClipStatusEnum.APPROVED, ClipStatusEnum.REJECTED]


class IntervalResponse(SourceInterval):
    text: str  # the current words of the interval, after any transcript correction


class ClipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    job_id: Optional[uuid.UUID]
    topic_id: Optional[uuid.UUID]
    status: ClipStatusEnum
    position: Position
    title: str
    rationale: str
    intervals: List[IntervalResponse]
    duration_seconds: Seconds
    warnings: List[ClipWarningEnum]
    score: Optional[Score]
    score_breakdown: Optional[Dict[ScoreCriterionEnum, Rating]]
    options: ClipOptions
    ai_generated: bool
    llm_provider: str
    llm_model: str
    prompt_versions: Dict[str, str]
    created_at: datetime
    updated_at: datetime
    reviewed_at: Optional[datetime]


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: Position
    first_sentence: Position
    last_sentence: Position
    start: Seconds
    end: Seconds
    title: str
    summary: str
    ai_generated: bool
    llm_provider: str
    llm_model: str


class ClipListResponse(BaseModel):
    job: Optional[JobStatusResponseSchema]  # the latest clip proposal job of the project, if any
    clips: List[ClipResponse]
```

## 7. LLM interface (T4.11, David)

The providers are built with LangChain, approved by the team (section 18): `ChatOllama` from `langchain-ollama` in `ollama.py` and `ChatOpenAI` from `langchain-openai` in `openai_compatible.py`. LangChain is imported only in those two files. The rest of the code talks only to `LLMClient` and never imports LangChain, so it can be replaced later without changing anything else.

Validation and retries stay in `LLMClient` (section 7.3), not in LangChain's output parsers or retry helpers: the behaviour is then the same for every provider, and the fake provider tests all of it.

### 7.1 Provider (`app/services/llm/provider.py`)

**[Contract PR]**

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from app.core.config import LLMRoleEnum
from app.schemas.clips import LLMInfo


@dataclass(frozen=True)
class LLMMessage:
    role: LLMRoleEnum  # system, user, assistant
    content: str


@dataclass(frozen=True)
class LLMRequest:
    prompt_name: str
    prompt_version: str
    messages: Sequence[LLMMessage]
    json_schema: Dict[str, Any]  # schema.model_json_schema() of the expected reply


@dataclass(frozen=True)
class LLMReply:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


# One request to a model, without retries or validation; LLMClient adds both.
# Source: NFR Maintainability (≥ 2 swappable LLM providers, configuration only).
class LLMProvider(ABC):

    @property
    @abstractmethod
    def info(self) -> LLMInfo:
        """Provider kind and model name, recorded with every AI output (FR16, FR18)."""

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMReply:
        """Blocking. Asks the server for JSON constrained to request.json_schema when it supports it
        (Ollama `format`, OpenAI-compatible `response_format` with `json_schema`).

        Raises LLMUnavailableError on connection errors, timeouts, HTTP 429/5xx or a missing model.
        """
```

### 7.2 Errors (`app/services/llm/errors.py`)

**[Contract PR]**

```python
class LLMError(RuntimeError):
    """Base class; RuntimeError as AGENTS.md asks for library failures."""


class LLMUnavailableError(LLMError):
    """The server cannot be reached, timed out or does not have the model."""


class LLMInvalidResponseError(LLMError):
    """The reply was not valid JSON for the schema after every allowed attempt."""
```

A wrong configuration (unknown profile, unknown provider kind, missing API key variable) raises `ValueError` when the client is built, so the worker fails at start-up instead of at the first job.

### 7.3 Client (`app/services/llm/client.py`)

**[Signature]** Implemented in T4.11 (David). The `...` bodies are not part of the contract; the behaviour listed below the block is.

```python
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMCallRecord:
    prompt_name: str
    prompt_version: str
    provider: str
    model: str
    attempts: int
    duration_seconds: float
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    succeeded: bool


class LLMClient:
    """One per job: it keeps the records of the calls made for that job."""

    def __init__(self, provider: LLMProvider) -> None: ...

    @property
    def info(self) -> LLMInfo: ...

    @property
    def calls(self) -> Tuple[LLMCallRecord, ...]: ...

    def complete_json(self, prompt: Prompt, schema: Type[T]) -> T: ...
```

Behaviour of `complete_json`, fixed by this contract:

1. Sends `[system, user]` messages from the rendered prompt and `schema.model_json_schema()`.
2. Removes any `<think>...</think>` block (Qwen3 reasoning) and surrounding whitespace before parsing.
3. Parses with `schema.model_validate_json`. On `ValidationError` it appends the bad reply as an `assistant` message and a `user` message built from `LLM_RETRY_FEEDBACK` (which includes the validation errors), then asks again. After `LLM_MAX_ATTEMPTS` attempts in total it raises `LLMInvalidResponseError`.
4. `LLMUnavailableError` from the provider is retried `LLM_UNAVAILABLE_RETRIES` times, `LLM_UNAVAILABLE_BACKOFF_SECONDS` apart, then re-raised.
5. Every call, successful or not, adds an `LLMCallRecord` and logs one INFO line with `LOG_LLM_CALL` (prompt name and version, provider, model, attempts, seconds, tokens). The prompt and reply texts are logged at DEBUG only when `LLM_LOG_CONTENT=true`, because they contain transcript text (personal data).
6. It never changes the meaning of a reply: no repairing of JSON, no guessing of missing fields.

Worst case for one call: `LLM_TIMEOUT_SECONDS × LLM_MAX_ATTEMPTS × (LLM_UNAVAILABLE_RETRIES + 1)` (240 s × 3 × 2 = 24 min with the defaults) must stay below `JOB_STALLED_AFTER_SECONDS` (30 min), or the sweep would fail a job that is still working. A test checks this with the defaults.

### 7.4 Prompts (`app/services/llm/prompts.py`)

**[Signature]** Implemented in T4.11 (David). The prompt texts are written by Murilo in T4.12, T4.13 and T4.15 (section 16).

```python
@dataclass(frozen=True)
class Prompt:
    name: str
    version: str  # first PROMPT_VERSION_LENGTH hex characters of the SHA-256 of both files
    system: str
    user: str


def render_prompt(name: str, **variables: str) -> Prompt:
    """Reads app/prompts/{name}.system.txt and {name}.user.txt and fills $variables with string.Template.

    A missing variable raises ValueError; an unused one too, so prompt files and code cannot drift apart.
    """
```

- `string.Template` (`$variable`) is used because prompts contain JSON braces.
- Prompt files are read once per process and cached.
- The version is recorded with every AI output, so the audit log and the evaluation (T4.27) know exactly which prompt produced a clip.
- User text (`topic`, `audience`) is inserted only after `clean_user_text`: control characters and line breaks replaced by spaces, length already limited by `ClipOptions`. The prompts place it inside a delimited block and tell the model it is data, not instructions (prompt injection).

### 7.5 Configuration and factory (`app/services/llm/factory.py`, `app/core/llm.toml`)

**[Fixed format]** `llm.toml` and the factory are written in T4.11 (David). The structure of the file and the profile names are fixed; the model names and values can be tuned in T4.11 without a contract change.

Precedence: **environment variable > profile in `llm.toml` > default in `config.py`**.

```toml
# app/core/llm.toml – LLM profiles; select one with LLM_PROFILE. No secrets here: API keys come from
# the environment variable named in api_key_env.
default_profile = "ollama-qwen"

[profiles.ollama-qwen]          # project VM
provider = "ollama"
base_url = "http://ollama:11434"
model = "qwen3:8b"
context_tokens = 16384

[profiles.ollama-small]         # development laptops
provider = "ollama"
base_url = "http://ollama:11434"
model = "qwen3:1.7b"
context_tokens = 8192

[profiles.openai-compatible]    # any self-hosted OpenAI-compatible server (vLLM, llama.cpp, LM Studio)
provider = "openai_compatible"
base_url = "http://vllm:8000/v1"
model = "Qwen/Qwen3-8B"
api_key_env = "LLM_API_KEY"
```

Profile fields and their `config.py` defaults: `provider`, `base_url`, `model`, `api_key_env` (none), `context_tokens` (`DEFAULT_LLM_CONTEXT_TOKENS`), `max_output_tokens` (`DEFAULT_LLM_MAX_OUTPUT_TOKENS`), `temperature` (`DEFAULT_LLM_TEMPERATURE`, 0.0), `seed` (`DEFAULT_LLM_SEED`), `timeout_seconds` (`DEFAULT_LLM_TIMEOUT_SECONDS`), `think` (`DEFAULT_LLM_THINK`, false).

`context_tokens` is passed to Ollama as `num_ctx`. Ollama's own default is small and silently cuts long prompts, so it must always be set.

`get_llm_provider() -> LLMProvider` reads `get_llm_settings()` (cached, like `get_settings()`) and builds the provider for `LlmProviderEnum.OLLAMA` or `LlmProviderEnum.OPENAI_COMPATIBLE`. There is no "fake" provider in the application: the fake lives in the tests.

### 7.6 Fake provider (`backend/tests/fake_llm_provider.py`)

**[Contract PR]** Test code, so its literal values stay inline (test inputs, `AGENTS.md`).

```python
from typing import Callable, Dict, List, Mapping, Sequence, Union

from app.schemas.clips import LLMInfo
from app.services.llm.provider import LLMProvider, LLMReply, LLMRequest

Scripted = Union[str, Exception, Callable[[LLMRequest], str]]

FAKE_INFO = LLMInfo(provider="fake", model="fake-model")


class FakeLLMProvider(LLMProvider):
    """Replies with scripted text per prompt name, in order, and records every request it receives."""

    def __init__(self, replies: Mapping[str, Sequence[Scripted]], info: LLMInfo = FAKE_INFO) -> None:
        self._replies: Dict[str, List[Scripted]] = {name: list(items) for name, items in replies.items()}
        self._info = info
        self.requests: List[LLMRequest] = []

    @property
    def info(self) -> LLMInfo:
        return self._info

    def generate(self, request: LLMRequest) -> LLMReply:
        self.requests.append(request)
        remaining = self._replies.get(request.prompt_name)
        assert remaining, f"No scripted reply left for prompt {request.prompt_name!r}"
        item = remaining.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMReply(text=item(request) if callable(item) else item)
```

- A `str` item is returned as the reply text; an `Exception` item is raised (for example `LLMUnavailableError()`); a callable builds the reply from the request (useful for replies that depend on the sentence numbers sent).
- Running out of scripted replies for a prompt fails the test with a clear `AssertionError`.
- Both owners use only this fake in automated tests: no test depends on network, Ollama or Langfuse.

## 8. Step functions

**[Signature]** Each function is implemented in the task named in section 3. Only the name, module, parameters, return type and guarantees are fixed here.

Every function below is pure apart from its LLM calls: no database, no object storage, no events. Each gets the short banner comment with a `Source:` line required by `AGENTS.md`.

| Function | Module | Owner | Signature | Guarantees |
| --- | --- | --- | --- | --- |
| `build_sentences` | `services/clips/sentences.py` | Murilo | `(document: TranscriptDocument) -> List[Sentence]` | section 5.1; indexes 0..n-1 with no gaps; every word in exactly one sentence |
| `format_sentences` | `services/clips/sentences.py` | Murilo | `(sentences: Sequence[Sentence]) -> str` | section 5.2 |
| `segment_topics` | `services/clips/topics.py` | Murilo | `(llm: LLMClient, sentences: Sequence[Sentence], language: str, report: ProgressCallback) -> List[Topic]` | section 8.1 |
| `propose_candidates` | `services/clips/candidates.py` | Murilo | `(llm: LLMClient, topic: Topic, sentences: Sequence[Sentence], options: ClipOptions, language: str) -> List[ClipCandidate]` | section 8.2 |
| `validate_candidates` | `services/clips/validation.py` | David | `(candidates: Sequence[ClipCandidate], sentences: Sequence[Sentence], topics: Sequence[Topic], options: ClipOptions) -> ValidationResult` | section 9 |
| `build_intervals` | `services/clips/validation.py` | David | `(ranges: Sequence[SentenceRange], sentences: Sequence[Sentence]) -> List[SourceInterval]` | public, reused by the editor (T4.19) |
| `rate_clips` | `services/clips/rating.py` | Murilo | `(llm: LLMClient, clips: Sequence[ClipProposal], sentences: Sequence[Sentence], options: ClipOptions, language: str) -> List[ClipRating]` | section 10 |
| `rank_clips` | `services/clips/ranking.py` | David | `(clips: Sequence[ClipProposal], ratings: Optional[Sequence[ClipRating]], options: ClipOptions) -> ValidationResult` | section 10 |
| `run_clip_proposal` | `services/workflow/clip_proposal_pipeline.py` | David | `(storage: LocalStorage, object_storage: ObjectStorage, provider: LLMProvider, request: JobRequestMessage, emit: EventEmitter) -> JobUpdateEventSchema` | section 11 |

`language` is `TranscriptDocument.language`; prompts ask for titles, summaries and rationales in that language.

### 8.1 `segment_topics` (T4.12)

- Splits the sentences into windows of `TOPIC_WINDOW_SENTENCES` (150) with `TOPIC_WINDOW_OVERLAP_SENTENCES` (20) of overlap; one `topic_segmentation` call per window; calls `report(percent)` after each window.
- Merges the windows into one list. The merge rule is Murilo's choice, but the result must satisfy:
  - topics are ordered; the first starts at sentence 0, the last ends at the last sentence;
  - each topic starts at the sentence after the previous one ends (no gaps, no overlaps);
  - a topic shorter than `TOPIC_MIN_SECONDS` (60 s) is joined to its neighbour, except when it is the only topic;
  - `first_word`, `last_word`, `start`, `end` are copied from the sentences, never from the LLM.
- Sentence numbers in the reply that are out of the window are clamped to it; the coverage is then repaired in code (each topic starts after the previous one; the last one extends to the end). The LLM's boundaries are a suggestion, the invariants are enforced by code.

### 8.2 `propose_candidates` (T4.13)

- One `clip_candidates` call per topic with that topic's sentences, the options and `CLIP_MAX_CANDIDATES_PER_TOPIC` (3).
- Returns the candidates as the model gave them, with `topic_position` set, keeping at most `CLIP_MAX_CANDIDATES_PER_TOPIC`. It does not check sentence numbers or durations: that is validation's job, so the discard reasons are counted in one place.

## 9. Validation (T4.14, David)

Deterministic Python, no LLM. Candidates are processed in topic order, then in reply order. The first rule that fails discards the candidate with its reason.

1. **Unknown sentences.** A range with a number outside `0..len(sentences)-1` → `unknown_sentence`.
2. **Normalise ranges.** Sort by `first`; merge ranges that overlap or touch (`next.first <= previous.last + 1`). Clips proposed by the AI always play in the order of the original; reordering is a human edit (FR12).
3. **Duration** = sum over the ranges of `sentences[last].end - sentences[first].start`.
4. **Too long.** While the duration is above `max_duration_seconds` and the clip has more than one sentence, remove the last sentence (a range left empty is removed). Still too long → `too_long`. Any removal adds the warning `duration_adjusted`.
5. **Too short.** While the duration is below `min_duration_seconds`: add the sentence after the end of the last range if it belongs to the same topic and does not push the duration above the maximum; otherwise add the sentence before the start of the first range under the same conditions; if neither is possible → `too_short`. Any addition adds `duration_adjusted`. The clip therefore always starts and ends on sentence boundaries.
6. **Fabricated quotes.** Every fragment between quotation marks (`QUOTE_PATTERNS`: `"…"`, `“…”`, `«…»`) in the title or the rationale must appear in the clip's text after normalisation (lower case, collapsed whitespace, punctuation removed at both ends) → otherwise `fabricated_quote`.
7. **Context loss.** More than one range after normalisation → warning `context_loss` (FR11): the clip joins parts of the original that are not consecutive.
8. **Intervals.** One `SourceInterval` per range with `build_intervals`: sentence numbers, `first_word` of the first sentence, `last_word` of the last sentence, `start` and `end` from those words. Exact word times, no padding: padding, if any, is a rendering choice (T4.21).
9. **Duplicates.** Overlap with an already accepted clip = shared seconds / duration of the shorter clip. At or above `CLIP_DUPLICATE_OVERLAP_RATIO` (0.8) → `duplicate`; the earlier clip is kept.
10. **Position.** Accepted clips get `position` in order of their first `start`.

## 10. Rating and ranking (T4.15, Extra)

Controlled by `CLIP_RANKING_ENABLED` (env, default `false` until T4.15 is merged). Without it, `rank_clips(clips, None, options)` returns the clips in video order with `score = None`, and the `ranking_clips` step is skipped.

- `rate_clips` (Murilo) sends the validated clips to the `clip_rating` prompt in batches of `CLIP_RATING_BATCH_SIZE` (8), numbered from 0 within each batch, and asks for a 1–5 rating for each criterion of `ScoreCriterionEnum`: `completeness`, `rigour`, `standalone` (understandable out of context), `topic_match`. `topic_match` is only asked when `options.topic` is set. It maps the batch numbers back to `clip_position`.
- `rank_clips` (David): `score = Σ w_c × (rating_c − RATING_MIN) / (RATING_MAX − RATING_MIN)` over the rated criteria, with `CLIP_SCORE_WEIGHTS` renormalised to sum 1 over those criteria. Defaults: completeness 0.30, rigour 0.30, standalone 0.25, topic_match 0.15.
- Sort by score (descending), then by time in the video. Clips without a rating go after the rated ones, in video order. Keep the first `CLIP_MAX_PROPOSALS` (10); the rest are discarded with `below_rank`. `position` is renumbered from 0.

## 11. The clip proposal job (T4.16)

### 11.1 Job type, parameters and request message

- `JobTypeEnum.CLIP_PROPOSAL = "clip_proposal"`; queue `jobs.clip_proposal` (from `JOBS_QUEUE_FORMAT`).
- At most one active clip proposal job per project: partial unique index `uq_jobs_one_active_clip_proposal_per_project`, like ingestion and transcription.
- New member of the `JobParameters` union in `schemas/job.py` (**[Contract PR]**):

```python
class ClipProposalParams(_StrictModel):
    job_type: Literal["clip_proposal"] = "clip_proposal"
    transcript_id: UUID
    options: ClipOptions
```

- New optional field in `JobRequestMessage`, set by the API only: `transcript_key: str | None = None`, the object storage key of the transcript snapshot.
- `Job.media_asset_id` is the transcript's media asset.

### 11.2 Steps, messages and progress weights

| Step (`JobStepProcessingEnum`) | Message (`JOB_STEP_MESSAGES`) | Weight (start, end) |
| --- | --- | --- |
| `initializing` | "Reading the transcript" | (0, 5) |
| `segmenting_topics` (new) | "Finding the topics" | (5, 35) |
| `proposing_clips` (new) | "Selecting clip candidates" | (35, 75) |
| `validating_clips` (new) | "Checking the clips against the transcript" | (75, 80) |
| `ranking_clips` (new) | "Ranking the clips" | (80, 90) |
| `persisting_results` | "Saving the proposals" | (90, 95) |
| `cleaning_up` | "Cleaning up temporary files" | (95, 100) |
| `finished` | "Clip proposals ready" | (100, 100) |

`proposing_clips` reports `100 × topics done / topics` after each topic. Steps are only reported forward; a skipped step (ranking disabled) is simply not reported.

### 11.3 What `run_clip_proposal` does

1. `initializing`: downloads `request.transcript_key` to `MEDIA_ROOT/projects/{project_id}/clips/{job_id}/`, validates it as `TranscriptDocument`, builds the sentences, creates `LLMClient(provider)`.
2. `segmenting_topics` → `segment_topics`.
3. `proposing_clips` → `propose_candidates` for every topic.
4. `validating_clips` → `validate_candidates`.
5. `ranking_clips` → `rate_clips` + `rank_clips` when enabled; otherwise `rank_clips(clips, None, options)` without reporting the step.
6. `persisting_results`: writes `ClipProposalDocument` to `clips/{job_id}/proposals.json` in object storage.
7. `cleaning_up`: removes the local directory; publishes `completed` with `ClipProposalOutput`.

Zero valid clips is a **completed** job with `clip_count = 0`; the interface explains that no excerpt matched the options.

Failures follow the transcription pipeline: the local directory is removed and a `failed` event is published.

| Exception | `JobErrorCodeEnum` | Message |
| --- | --- | --- |
| `LLMUnavailableError` | `model_unavailable` (exists) | `ERROR_LLM_UNAVAILABLE` |
| `LLMInvalidResponseError` | `llm_invalid_response` (new) | `ERROR_LLM_INVALID_RESPONSE` |
| `ValueError`, `FileNotFoundError` (missing or invalid snapshot) | `invalid_source` (exists) | the exception text |
| `ObjectStorageError` | `internal_error` | `ERROR_STORAGE_UNAVAILABLE` |
| anything else | `internal_error` | `ERROR_CLIP_PROPOSAL_INTERNAL`, logged with the traceback, re-raised |

### 11.4 Worker (Murilo)

`ClipWorker(JobWorker)` with `job_type = JobTypeEnum.CLIP_PROPOSAL`; `run_job` calls `run_clip_proposal(storage, object_storage, provider, request, self._emit)`. `main()` builds the provider once with `get_llm_provider()`. New `clip-worker` service in `docker-compose.yml`, from the backend image, command `python -m app.workers.clip_worker`, with the `LLM_*` and `CLIP_RANKING_ENABLED` variables.

## 12. Persistence (T4.16a, Murilo)

Migration `0010_topics_and_clips` (after `0009_transcripts`; one Alembic head). Literal values only, no `config.py` import.

**`topics`**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `project_id` | FK projects, CASCADE, index | |
| `transcript_id` | FK transcripts, CASCADE | |
| `job_id` | FK jobs, SET NULL | |
| `position` | int | unique with `transcript_id` |
| `first_sentence`, `last_sentence`, `first_word`, `last_word` | int | |
| `start_seconds`, `end_seconds` | float | |
| `title`, `summary` | text | |
| `ai_generated` | bool, default true | FR16 |
| `llm_provider`, `llm_model` | string | |
| `prompt_version` | string | |
| `created_at` | timestamp | |

**`clips`**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `project_id` | FK projects, CASCADE, index | |
| `transcript_id` | FK transcripts, CASCADE | |
| `job_id` | FK jobs, SET NULL | |
| `topic_id` | FK topics, SET NULL | |
| `status` | `ClipStatusEnum` (string column, `enum_type`) | index with `project_id` |
| `position` | int | |
| `title`, `rationale` | text | |
| `intervals` | JSONB | list of `SourceInterval`, in play order |
| `duration_seconds` | float | |
| `warnings` | JSONB | list of `ClipWarningEnum` |
| `score` | float, nullable | |
| `score_breakdown` | JSONB, nullable | |
| `options` | JSONB | the `ClipOptions` used |
| `ai_generated` | bool, default true | FR16 |
| `llm_provider`, `llm_model` | string | |
| `prompt_versions` | JSONB | |
| `created_at`, `updated_at` | timestamp | |
| `reviewed_at` | timestamp, nullable | last approval or rejection |

`record_clip_proposal_outcome(db, job, open_object_storage)`, called by the event consumer like `record_transcription_outcome`:

- `completed`: loads and validates the `ClipProposalDocument`; if its transcript no longer exists the result is dropped (logged). Otherwise it deletes the project's previous topics and its clips in status `proposed` or `rejected` (approved clips stay, their `topic_id` becomes null), inserts the new topics and clips with status `proposed`, and writes the audit entries of section 13.
- `failed`: audit `clip_proposal.failed` with the job ID and error code.
- The project status does not change: clip proposals are tracked by their job.

Other rules:
- Deleting a project or its account removes topics and clips (CASCADE) and the `clips/` objects with the rest of the project's storage; audit entries stay (MS3 1.4.3).
- A new ingestion is refused while a clip proposal job of the project is active (`ERROR_INGESTION_DURING_CLIP_PROPOSAL`, 409), like during a transcription.

## 13. Audit log (FR18)

New `AuditAction` values; `actor` is the user for user actions and `None` (system) for worker results.

| Action | Actor | `details` |
| --- | --- | --- |
| `clip_proposal.requested` | user | `job_id`, `transcript_id`, `options` |
| `topics.generated` | system | `job_id`, `topic_count`, `llm_provider`, `llm_model`, `prompt_version` |
| `clip.proposed` | system | `clip_id`, `job_id`, `title`, `rationale`, `intervals`, `warnings`, `score`, `llm_provider`, `llm_model`, `prompt_versions`, `ai_generated: true` |
| `clip_proposal.completed` | system | `job_id`, `clip_count`, `discarded_count` |
| `clip_proposal.failed` | system | `job_id`, `error_code` |
| `clip.approved` | user | `clip_id`, `previous_status` |
| `clip.rejected` | user | `clip_id`, `previous_status` |

One `clip.proposed` entry per clip, so the rationale and source of 100% of AI-proposed clips is in the log (NFR Security / ethics). Reserved for later tasks: `clip.edited` (T4.19), `clip.metadata_generated` (T4.23).

## 14. API (T4.16a, Murilo; for Daniel and Lucas)

All routes require a session and project ownership (`require_project_access`): 401 without a session, 404 for another user's project.

| Method and route | Body | Success | Errors |
| --- | --- | --- | --- |
| `POST /projects/{project_id}/clips` | `ClipOptions` | 202 `JobStatusResponseSchema` | 403 licence not confirmed (FR01); 409 no finished transcript (`ERROR_CLIPS_TRANSCRIPT_NOT_READY`); 409 a clip job is already running; 422 invalid options; 503 broker down |
| `GET /projects/{project_id}/clips` | query `status` (optional) | 200 `ClipListResponse` | — |
| `GET /projects/{project_id}/clips/{clip_id}` | — | 200 `ClipResponse` | 404 |
| `PATCH /projects/{project_id}/clips/{clip_id}` | `ClipStatusUpdate` | 200 `ClipResponse` | 404; 422 |
| `GET /projects/{project_id}/topics` | — | 200 `List[TopicResponse]` | — |

- `POST` writes the snapshot `clips/{job_id}/transcript.json`: the current transcript from the database (with any correction from T4.9) as a `TranscriptDocument`, word positions unchanged. It is the exact text the AI saw (FR11), and it stays until the project is deleted.
- `GET /clips` lists clips by `position`; `job` is the latest clip proposal job, so the page shows progress or failure without another request. Progress is pushed on `WS /projects/{project_id}/progress`; the frontend reads `job_type` to tell clip jobs from the others.
- `IntervalResponse.text` is built from the current words of the transcript (`first_word..last_word`), so a corrected word shows corrected text. The transcript is never rewritten (FR15).
- `PATCH` with the current status changes nothing and writes no audit entry. Any other change sets `reviewed_at` and writes `clip.approved` or `clip.rejected`.

Example `GET /projects/{project_id}/clips`:

```json
{
  "job": {
    "job_id": "8b0e…",
    "project_id": "2f6c…",
    "job_type": "clip_proposal",
    "status": "completed",
    "step": "finished",
    "progress": 100.0,
    "message": "Clip proposals ready",
    "output": {"clip_count": 1, "topic_count": 6, "...": "..."}
  },
  "clips": [
    {
      "id": "c41a…",
      "project_id": "2f6c…",
      "job_id": "8b0e…",
      "topic_id": "a9d2…",
      "status": "proposed",
      "position": 0,
      "title": "Why inflation fell in 2024",
      "rationale": "Complete argument: states the fact, then explains its three causes.",
      "intervals": [
        {
          "first_sentence": 42, "last_sentence": 47,
          "first_word": 812, "last_word": 905,
          "start": 723.48, "end": 771.02,
          "text": "Inflation in 2024 was lower than expected. This is mainly due to three factors. …"
        }
      ],
      "duration_seconds": 47.54,
      "warnings": [],
      "score": null,
      "score_breakdown": null,
      "options": {"min_duration_seconds": 15, "max_duration_seconds": 60, "topic": "economy",
                  "audience": null, "aspect_ratio": "9:16"},
      "ai_generated": true,
      "llm_provider": "ollama",
      "llm_model": "qwen3:8b",
      "prompt_versions": {"topic_segmentation": "3f9a1c2b7e4d", "clip_candidates": "a01b9e44c2f0"},
      "created_at": "2026-12-04T15:02:11Z",
      "updated_at": "2026-12-04T15:02:11Z",
      "reviewed_at": null
    }
  ]
}
```

A copy of this example is saved as `frontend/src/data/clips.sample.json` by whoever starts T4.17 or T4.18, so both pages use the same sample data until the API is ready.

## 15. `config.py` additions

Three sections, added in this order at the end of the existing constants (before `_csv`). Values are proposals; names are fixed by the contract.

### 15.1 "Clip generation – shared"

**[Contract PR]** Everything in this subsection, because `schemas/clips.py` and the job model need it from day 1.

```python
class AspectRatioEnum(str, Enum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"


class ClipStatusEnum(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ClipWarningEnum(str, Enum):
    CONTEXT_LOSS = "context_loss"
    DURATION_ADJUSTED = "duration_adjusted"


class DiscardReasonEnum(str, Enum):
    UNKNOWN_SENTENCE = "unknown_sentence"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    FABRICATED_QUOTE = "fabricated_quote"
    DUPLICATE = "duplicate"
    BELOW_RANK = "below_rank"


class ScoreCriterionEnum(str, Enum):
    COMPLETENESS = "completeness"
    RIGOUR = "rigour"
    STANDALONE = "standalone"
    TOPIC_MATCH = "topic_match"


class LLMRoleEnum(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LlmProviderEnum(str, Enum):
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
```

Additions to existing definitions: `JobTypeEnum.CLIP_PROPOSAL`; `JobStepProcessingEnum.SEGMENTING_TOPICS`, `PROPOSING_CLIPS`, `VALIDATING_CLIPS`, `RANKING_CLIPS`; `JobErrorCodeEnum.LLM_INVALID_RESPONSE`; the `AuditAction` values of section 13; the `JOB_STEP_MESSAGES` and `JOB_STEP_WEIGHTS` entries of section 11.2; `JOB_ACTIVE_CLIP_PROPOSAL_INDEX`.

Constants: `FIRST_POSITION = 0`, `CLIP_MIN_SECONDS = 5`, `CLIP_MAX_SECONDS = 180`, `CLIP_DEFAULT_MIN_SECONDS = 15`, `CLIP_DEFAULT_MAX_SECONDS = 60` (NFR Performance), `CLIP_TOPIC_MAX_LENGTH = 200`, `CLIP_AUDIENCE_MAX_LENGTH = 200`, `CLIP_TITLE_MAX_LENGTH = 120`, `CLIP_RATIONALE_MAX_LENGTH = 600`, `CHAPTER_TITLE_MAX_LENGTH = 120`, `CHAPTER_SUMMARY_MAX_LENGTH = 600`, `CLIP_MAX_RANGES = 3`, `RATING_MIN = 1`, `RATING_MAX = 5`, `SCORE_MIN = 0.0`, `SCORE_MAX = 1.0`, `ERROR_RANGE_ORDER`, `ERROR_CLIP_DURATION_ORDER`, `CLIPS_DIR = "clips"`, `CLIP_TRANSCRIPT_FILE = "transcript.json"`, `CLIP_PROPOSALS_FILE = "proposals.json"`, `PROMPT_TOPIC_SEGMENTATION = "topic_segmentation"`, `PROMPT_CLIP_CANDIDATES = "clip_candidates"`, `PROMPT_CLIP_RATING = "clip_rating"`, `PROMPT_CLIP_METADATA = "clip_metadata"` (reserved for T4.23).

### 15.2 "LLM layer" (David)

**[Fixed format]** The names are fixed; each constant is added by the task that first uses it (T4.11, T4.14, T4.15, T4.16b).

| Environment variable | `Settings` field | Default |
| --- | --- | --- |
| `LLM_CONFIG_FILE` | `llm_config_file` | `app/core/llm.toml` |
| `LLM_PROFILE` | `llm_profile` | `default_profile` of the file |
| `LLM_BASE_URL` | override | profile value |
| `LLM_MODEL` | override | profile value |
| `LLM_TIMEOUT_SECONDS` | override | `DEFAULT_LLM_TIMEOUT_SECONDS = 240` |
| `LLM_API_KEY` | read through `api_key_env` | none; only in `.env`, never committed or logged |
| `LLM_LOG_CONTENT` | `llm_log_content` | `false` |

Constants: `DEFAULT_LLM_CONTEXT_TOKENS = 16384`, `DEFAULT_LLM_MAX_OUTPUT_TOKENS = 2048`, `DEFAULT_LLM_TEMPERATURE = 0.0`, `DEFAULT_LLM_SEED = 42`, `DEFAULT_LLM_THINK = False`, `LLM_MAX_ATTEMPTS = 3`, `LLM_UNAVAILABLE_RETRIES = 1`, `LLM_UNAVAILABLE_BACKOFF_SECONDS = 10.0`, `LLM_RETRY_FEEDBACK`, `LLM_THINK_BLOCK_PATTERN`, `PROMPTS_DIR`, `PROMPT_SYSTEM_SUFFIX = ".system.txt"`, `PROMPT_USER_SUFFIX = ".user.txt"`, `PROMPT_VERSION_LENGTH = 12`, the Ollama and OpenAI-compatible paths and JSON keys that are not library interface names, `ERROR_LLM_UNAVAILABLE`, `ERROR_LLM_INVALID_RESPONSE`, `ERROR_LLM_PROFILE_UNKNOWN`, `ERROR_LLM_PROVIDER_UNKNOWN`, `ERROR_LLM_API_KEY_MISSING`, `ERROR_PROMPT_VARIABLES`, `LOG_LLM_CALL`, `LOG_LLM_CONTENT`.

Validation and ranking constants (David): `CLIP_DUPLICATE_OVERLAP_RATIO = 0.8`, `QUOTE_PATTERNS`, `CLIP_SCORE_WEIGHTS`, `CLIP_MAX_PROPOSALS = 10`, `DEFAULT_CLIP_RANKING_ENABLED = "false"` (env `CLIP_RANKING_ENABLED`), `ERROR_CLIP_PROPOSAL_INTERNAL`, `LOG_CLIP_PROPOSAL_FAILED`.

### 15.3 "Clip proposals" (Murilo)

**[Fixed format]** The names are fixed; each constant is added by the task that first uses it (sentences, T4.12, T4.13, T4.15, T4.16a).

`SENTENCE_END_CHARACTERS`, `SENTENCE_ABBREVIATIONS`, `SENTENCE_MAX_PAUSE_SECONDS = 2.0`, `SENTENCE_MAX_WORDS = 60`, `SENTENCE_MAX_SECONDS = 20.0`, `PROMPT_TIMECODE_FORMAT`, `PROMPT_TIMECODE_FORMAT_HOURS`, `PROMPT_SENTENCE_LINE`, `PROMPT_SENTENCE_LINE_NO_SPEAKER`, `TOPIC_WINDOW_SENTENCES = 150`, `TOPIC_WINDOW_OVERLAP_SENTENCES = 20`, `TOPIC_MIN_SECONDS = 60`, `CLIP_MAX_CANDIDATES_PER_TOPIC = 3`, `CLIP_RATING_BATCH_SIZE = 8`, `PROMPT_NOT_SET = "not specified"`, `TABLE_TOPICS`, `TABLE_CLIPS`, `FK_TOPIC_ID`, route constants (`CLIPS_ROUTE_TAG`, `CLIPS_ROUTE`, `CLIP_ROUTE`, `TOPICS_ROUTE`), `ERROR_CLIPS_TRANSCRIPT_NOT_READY`, `ERROR_CLIP_PROPOSAL_ALREADY_RUNNING`, `ERROR_INGESTION_DURING_CLIP_PROPOSAL`, `ERROR_CLIP_NOT_FOUND`, `AUDIT_DETAIL_*` keys used in section 13.

`.env.example` gains `LLM_PROFILE`, `LLM_CONFIG_FILE`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_API_KEY=` (empty), `LLM_LOG_CONTENT=false`, `CLIP_RANKING_ENABLED=false`.

## 16. Prompts (Murilo)

Files in `backend/app/prompts/`: `{name}.system.txt` and `{name}.user.txt`. Written in English (`AGENTS.md`); the model writes titles, summaries and rationales in `$language`.

| Prompt | Variables | Reply schema |
| --- | --- | --- |
| `topic_segmentation` | `language`, `first_sentence`, `last_sentence`, `sentences` | `TopicReply` |
| `clip_candidates` | `language`, `topic_title`, `topic_summary`, `sentences`, `min_duration_seconds`, `max_duration_seconds`, `topic`, `audience`, `max_candidates` | `CandidateReply` |
| `clip_rating` | `language`, `clips`, `topic`, `audience`, `criteria` | `RatingReply` |

Every prompt must:
- answer only with JSON for its schema (the schema is also sent to the server);
- refer to the transcript only by sentence numbers shown in the prompt; never copy, rewrite or quote the speech;
- for candidates: start where an argument starts and end where it concludes, never cut an idea in half, put rigour and completeness before virality, prefer excerpts that are understandable without the rest of the talk, respect the duration range using the durations shown, return at most `$max_candidates`, and return an empty list when nothing fits (FR10);
- treat `$topic` and `$audience` as data inside a delimited block, not as instructions;
- use only synthetic examples (few-shot), never real transcripts.

When `topic` or `audience` is not set, the variable is `PROMPT_NOT_SET` ("not specified").

## 17. Test data and tests

| Data | Owner | Content |
| --- | --- | --- |
| `tests/data/clips/short_transcript.json` | David, contract PR | Synthetic `TranscriptDocument` in European Portuguese, about 40 sentences in 3 clear topics, with the edge cases of section 5.1: abbreviations, a long pause, a 60-word unpunctuated run, a sentence across two segments. Unblocks both owners from day 1. |
| `tests/data/clips/lecture_transcript.json` | Murilo | Real `TranscriptDocument` of a 10–20 min lecture exported from the VM. Only from a recording with documented permission (the T4.26 dataset or a CC licence); its source and licence go in `tests/data/clips/README.md`. |
| Fake replies | each owner | Inline in tests, or `tests/data/clips/replies/*.json` |

- Automated tests use only `FakeLLMProvider` and these files: no network, no LLM, no Langfuse; they run in CI.
- Optional real-model tests are marked `llm` and skipped unless `TEST_LLM_PROFILE` is set, in the style of `TEST_RABBITMQ_URL`. They never run in CI.
- End-to-end test (T4.16): API `POST /clips` → in-process dispatcher → `run_clip_proposal` with the fake provider → event consumer → `GET /clips` returns the clips and the audit log holds every entry of section 13.
- Pull requests that change prompts or the pipeline are run on the VM by Murilo before merging, with `LLM_LOG_CONTENT=true` on the test lecture only; the call log lines (or Langfuse links) are attached to the PR.

## 18. Decisions the team must approve

New dependencies and images need the team's approval (`AGENTS.md`). Apart from LangChain, which is approved, the contract does not depend on any of them.

| Item | Proposal | If not approved |
| --- | --- | --- |
| LangChain (`langchain-core`, `langchain-ollama`, `langchain-openai`) | **Approved.** Used only inside `ollama.py` and `openai_compatible.py` (section 7). The packages are added to `backend/requirements.txt` in T4.11, with a minimum version as for the other dependencies. | — |
| LangGraph | Not needed while the pipeline is a straight sequence. Decide at the 2 Dec checkpoint, only if the pipeline needs loops (for example, asking again when validation discards too much). | Plain sequence |
| Langfuse | Recent versions need PostgreSQL, ClickHouse, Redis and S3; `AGENTS.md` says Redis is not used, and the cloud version is excluded (personal data). Recommendation: not for the MVP; the call log of section 7.3 covers prompt tuning. | Call log only |
| `ollama/ollama` Docker image (pinned version) | New `ollama` service with an `ollama_models` volume; port 11434 published in development only. Laptops may instead run Ollama on the host (`LLM_BASE_URL=http://host.docker.internal:11434`, with `extra_hosts` on Linux). | Ollama installed on the VM host |
| Models | `qwen3:8b` on the VM, `qwen3:1.7b` on laptops; to confirm against the "Qwen3.8" in the MS3 licence audit. | — |
| `tomllib` | Standard library (Python 3.12 in the image); no new dependency. | — |

## 19. Delivery order

Each step is a small pull request to `develop` (1–2 days), reviewed by the other owner. Code for each step is shown for approval before it is written.

| # | Pull request | Owner | Depends on |
| --- | --- | --- | --- |
| 0 | Contract: this document and everything labelled **[Contract PR]**: `schemas/clips.py`, `ClipProposalParams` and `transcript_key` in `schemas/job.py`, the shared `config.py` section, `services/llm/provider.py` and `errors.py`, `tests/fake_llm_provider.py`, `short_transcript.json`. Definitions only, no logic. | David | — |
| 1 | Sentences (`build_sentences`, `format_sentences`) | Murilo | 0 |
| 2 | LLM layer, T4.11 (`client.py`, `prompts.py`, `ollama.py`, `openai_compatible.py`, `factory.py`, `llm.toml`, the LLM constants of section 15.2, the LangChain packages in `requirements.txt`) | David | 0 |
| 3 | Validation (T4.14) | David | 0 (tests with `short_transcript.json`; uses 1 once merged) |
| 4 | Job structure (T4.16a): models, migration, job type, worker, submission, results, API, audit | Murilo | 0 |
| 5 | Topics (T4.12) and its prompt | Murilo | 1, 2 |
| 6 | Pipeline (T4.16b), with the fake provider until 5 and 7 are merged | David | 2, 3, 4 |
| 7 | Candidates (T4.13) and its prompt | Murilo | 5 |
| 8 | Rating and ranking (T4.15, Extra) | both | 6, 7 |

Checkpoints: 2 Dec (0–4 merged; LangGraph decision), 6 Dec (pipeline with real topics and candidates on the VM), 8 Dec (end-to-end run, T4.31).

A piece is done when the acceptance criteria of its task are met, it has tests with the fake provider, CI is green, the other owner reviewed it and, for prompts or the pipeline, it ran on the VM.

## 20. Open points

- Whether the frontend aspect ratios `1:1` and `4:5` join `AspectRatioEnum` (the render task produces `16:9` and `9:16`).
- Performance on the VM (no GPU): the budget is 1 h of video → clips in ≤ 15 min for all stages (NFR Performance). Measured in T4.28; the knobs are the model, `TOPIC_WINDOW_SENTENCES` and `CLIP_MAX_CANDIDATES_PER_TOPIC`.
- Speaker labels in sentences depend on diarization (T4.8); until then prompts have no speakers.
- `docs/architecture.md` must record that clips have their own `clips` table (the domain model had none) and the new `clip-worker` and `ollama` services (T4.33).

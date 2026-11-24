# SynopStudio – Architecture

> Sources: MS2 architecture diagram (`SynopStudio_developmentdiagram`), MS2 Elaboration report (FR02 pipeline, NFRs), MS3 report §1.2 (component licence audit), domain model (`SynopStudio_DomainModel`).
> Items marked **(to confirm)** are not stated explicitly in those documents.

## 1. Overview

SynopStudio is a web application that turns long recordings (lectures, seminars, political debates, streams) into short clips for social media. A user uploads a video and optional context documents; an asynchronous AI pipeline transcribes, identifies speakers, segments by topic and proposes clips; the user reviews and edits them through a synchronized transcript, explicitly approves them, and exports them.

Core architectural principles (from the requirements):

- **Asynchronous processing.** Long jobs never block the API. The backend publishes jobs to a message broker and workers consume them.
- **Modular, replaceable components.** Transcription, LLM, captioning and reframing can be replaced independently (at least 5 deployable modules).
- **Open models, no provider lock-in.** LLM modules are open and swappable across at least 2 providers through configuration only.
- **Documented API.** At least 95% of endpoints documented with OpenAPI 3.x.
- **Traceability.** Every clip, caption and AI decision can be traced back to the original recording and logged.

## 2. Components

```
Browser (React)
   │  HTTP
Reverse proxy (Traefik) ──login──► Identity provider (Keycloak)
   │  REST                              ▲ token validation
Backend (FastAPI) ──────────────────────┘
   │  ├─ REST routers (API)
   │  ├─ WebSockets (progress events to the UI)
   │  └─ Business logic: Projects · Media and Upload · Transcripts · Segments · Clips · Editing
   │
   ├── PostgreSQL (relational data)
   ├── Object storage, S3-compatible (SeaweedFS): videos, audio, proxies, clips
   │
   └── AMQP ⇄ Message broker (RabbitMQ) ⇄ Workers
                                            ├─ Ingestion
                                            ├─ Document Parsing
                                            ├─ Audio and Speech
                                            ├─ AI and Summarization
                                            ├─ Highlight Scoring
                                            └─ Video Rendering and Reframing
                                            (workers read/write object storage directly)

External APIs ──events and data──► Backend
   (Email · Video sources · AI models)
```

| Component | Technology | Responsibility |
| --- | --- | --- |
| Frontend | React | Web interface: projects, transcript editor, timeline, clip review, export |
| Reverse proxy | Traefik | Entry point; routes HTTP requests to the backend and login to the identity provider |
| Identity provider | Keycloak | Login and user accounts; the backend validates its tokens |
| Backend | FastAPI (Python) | REST API, WebSocket notifications, business logic, publishing jobs and consuming results |
| Message broker | RabbitMQ (AMQP) | Job queue between backend and workers; workers publish results back |
| Workers | Python services | Long-running media and AI processing (see §3) |
| Relational database | PostgreSQL | Projects, metadata, transcripts, segments, clips, audit records |
| Object storage | SeaweedFS (S3 API) | Raw media, normalized audio, proxy videos, keyframes, rendered clips |
| External APIs | — | Email notifications, external video sources, external AI models |

### Backend business-logic modules

| Module | Main data (domain model) | Related requirements |
| --- | --- | --- |
| Projects | Project, Document, Keyword | FR01, FR03 |
| Media and Upload | MediaAsset, AudioTrack | FR02 |
| Transcripts | Transcript, TranscriptSegment, Speaker | FR04, FR05, FR06, FR13 |
| Segments | Topic | FR07, FR08 |
| Clips | MediaAsset (clips: relevance/highlight score, render status) | FR09, FR10, FR11, FR14–FR17, FR19 |
| Editing | Transcript edits, cuts, approvals | FR12, FR15, FR18 |

## 3. Workers and libraries

Libraries come from the MS3 licence audit. Which worker uses each library is inferred from their function **(to confirm)**. FFmpeg is used through PyAV, which bundles the FFmpeg libraries, and yt-dlp through its Python API; the `ffmpeg`, `ffprobe` and `yt-dlp` executables are never called directly.

| Worker | Job | Libraries / models |
| --- | --- | --- |
| Ingestion | Fetch or assemble the source, inspect it, extract audio, create proxy and keyframes | PyAV (FFmpeg libraries), yt-dlp Python API (authorised link import only) |
| Document Parsing | Extract text, headings and acronyms from context documents; build the project lexicon | pypdf, python-pptx, python-docx |
| Audio and Speech | Word-level transcription and speaker diarization | faster-whisper + CTranslate2, pyannote.audio |
| AI and Summarization | Terminology refinement, topic segmentation, clip proposals with rationale, titles/descriptions/keywords | Qwen (open LLM; version as in MS3 report: "Qwen3.8") |
| Highlight Scoring | Score segments for relevance (primary) and engagement (secondary) | **(to confirm)** |
| Video Rendering and Reframing | Cut, reframe 16:9 → 9:16, burn styled captions and effects, export | PyAV (FFmpeg libraries) |

## 4. Main processing flow

1. **Create project (FR01).** User registers title, authorship, speakers, date, licence and copyright notice. The pipeline cannot start without a valid licence and authorship confirmation.
2. **Ingest video (FR02).**
   - Direct upload: client checks extension and MIME type; chunked multipart upload to staging object storage.
   - Authorised link: backend validates the URL and access; the Ingestion worker fetches audio and video (up to 1080p) straight to storage. Only for videos the creator owns or is authorised to use, in line with the source platform's terms.
   - Optional start/end timecodes for partial ingestion.
   - Inspection with PyAV: headers, corrupted packets, variable frame rate, at least one audio track. Failures set project status to `Ingestion Failed` with error details.
   - Audio normalized to 16 kHz, 16-bit mono PCM WAV; waveform and volume profile generated.
   - Lightweight proxy (e.g. 720p H.264) and keyframe index for browser playback.
   - Technical metadata saved; an event triggers transcription.
   - Progress messages pushed to the UI ("Downloading from URL", "Extracting Audio").
3. **Parse context documents (FR03).** PDF, PPTX, DOCX, TXT → keyword and entity lexicon per project.
4. **Transcribe and diarize (FR04, FR05).** Word- and sentence-level timestamps; default European Portuguese, extensible to other languages; acoustic context profile tags.
5. **Refine terminology (FR06).** Low-confidence words compared against the project lexicon.
6. **Segment and index (FR07, FR08).** Topics, scenes and interventions; natural-language semantic search.
7. **Propose clips (FR09–FR11).** User sets duration, theme, audience and format; AI proposes clips prioritising rigor and completeness, each with a rationale, exact source intervals and context-loss warnings.
8. **Review and edit (FR12–FR15).** Transcript-based editing, confidence highlighting, reframing, mandatory explicit approval.
9. **Generate metadata and render (FR16, FR17).** AI titles/descriptions/tags labelled as AI-generated; rendering with captions and effects.
10. **Export (FR19).** Social-media presets, batch download, separate subtitle files (WebVTT), publishing metadata.
11. **Audit (FR18).** Every AI recommendation and user change is logged throughout.

## 5. Cross-cutting constraints

| Area | Constraint | Source |
| --- | --- | --- |
| Performance | UI actions < 200 ms; job submission < 5 s; 1 h recording → publishable clips in ≤ 15 min; videos up to 4 h | NFR Performance |
| Accuracy | Word timestamps and clip traceability ±100 ms; diarization ≥ 90% for up to 6 speakers | NFR Accuracy |
| Security | TLS 1.3 in transit; AES-256 at rest; licence confirmation on 100% of projects | NFR Security |
| Audit | Audit logs kept ≥ 12 months; rationale and source references for 100% of AI decisions | NFR Security; MS3 §1.4.3 |
| Data deletion | Deleting a project or account removes videos, documents, transcripts and clips; only billing and licence/editorial audit records remain (12 months) | MS3 §1.4.3 |
| AI transparency | AI-generated text labelled and marked in a machine-readable way (C2PA under evaluation) | MS3 §1.3.1, §1.3.4 |
| Licensing | Project released under Apache-2.0; no code copied from SupoClip (AGPL-3.0), used only as a design reference | MS3 §1.2 |

## 6. Open points (to confirm with the team)

- GPU requirements for workers. The Docker Compose services used so far are in `docker-compose.yml`.
- Queue names, message formats and retry/error policy for the workers not built yet. Ingestion defines them in `backend/app/core/config.py` and `backend/app/schemas/job.py`: no automatic retries, and a job that goes silent fails with the error code `timeout`.
- AES-256 at rest (NFR Security) currently covers the media in SeaweedFS. The encryption keys stay in the same volume as the data, the files of a running job are not encrypted, and transcripts do not exist yet.
- Signed media links (MS3 §1.1.6) have no owner check until the identity provider is in place.
- Model and library used by the Highlight Scoring worker.
- The domain model has no explicit `Clip`, `AuditLog`, `Approval` or `ShareLink` entity; clips appear to be represented by `MediaAsset` (relevance/highlight scores, render status).

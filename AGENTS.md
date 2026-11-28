# AGENTS.md

This file provides guidance to Agents when working with code in this repository.

## Project

SynopStudio turns long recordings (lectures, debates, conferences) into short, traceable
social-media clips through an asynchronous AI pipeline with mandatory human review.
Early stage: video ingestion (FR02) runs end to end on PostgreSQL, RabbitMQ and SeaweedFS; the frontend and the later pipeline stages are not built yet.

## Project documentation

- `docs/requirements.md` — actors, functional requirements FR01–FR19, NFR targets, legal/compliance rules. Read before implementing or changing any feature; cite requirement IDs.
- `docs/architecture.md` — target components, worker responsibilities, libraries per worker, end-to-end processing flow, open design points. Read before adding services, workers, queues or storage.
- `docs/llm-contract.md` — contract for AI clip generation (T4.11–T4.16): sentences, data formats, LLM interface, step functions and their owners, validation, the clip proposal job, database, audit log, API and `config.py` names. Read before working on the LLM layer or clip generation; changing it needs a contract pull request approved by both owners.

## Domain rules that affect code

- The AI pipeline must never start without a confirmed licence and authorship (FR01).
- Long-running work is always asynchronous: the API publishes jobs to RabbitMQ and workers process them; endpoints never block. Redis is not used.
- Every AI recommendation and every user change must be recorded in the audit log (FR18).
- AI-generated text must always be labelled as AI-generated, in a machine-readable way (FR16).
- Nothing is rendered or exported without explicit human approval; subtitles must match speech verbatim, no fabricated quotes (FR15).
- Every clip keeps a verifiable link to its exact source intervals (FR11).
- LLM providers must stay swappable through configuration only: environment variables plus a config file.
- Link import only for videos the creator owns or is authorised to use (FR02).
- Deleting a project/account removes videos, documents, transcripts and clips; only billing and licence/editorial audit records are retained (12 months).

## Folder structure

- `backend/app/main.py` — FastAPI app: `/health`, the routers from `app/api/`, the job event consumer and the periodic sweep.
- `backend/app/core/config.py` — all settings (from env vars) and constants.
- `backend/app/api/projects.py` — project endpoints: create and read (FR01), delete (US34).
- `backend/app/api/ingestion.py` — FR02 endpoints: `POST /projects/{id}/ingestions/url` (202, queues the job), `GET /projects/{id}/ingestion` (job + metadata) and `GET /projects/{id}/media` (signed temporary links to the proxy and the waveform).
- `backend/app/api/progress.py` — `WS /projects/{id}/progress`: job progress pushed to the client.
- `backend/app/api/uploads.py` — FR02 chunked upload: start, send chunks, resume (`GET`), complete (checks every chunk and queues the job).
- `backend/app/api/jobs.py` — `GET /projects/{id}/jobs/{job_id}`: the state of one job.
- `backend/app/api/errors.py` — maps service exceptions to HTTP errors (403/404/409/422/503) for all routers.
- `backend/app/services/video/ingestion.py` — media ingestion functions (PyAV + yt-dlp Python API).
- `backend/app/services/video/sources.py` — remote source checks before download: URL whitelist, yt-dlp metadata probe, time range validation.
- `backend/app/services/video/uploads.py` — upload sessions (PostgreSQL); the chunks go to object storage as a multipart upload.
- `backend/app/services/video/metadata.py` — technical metadata and the output of an ingestion (FR02 step 6).
- `backend/app/services/video/playback.py` — signed temporary links to a finished video (MS3 §1.1.6).
- `backend/app/services/storage/object_storage.py` — `ObjectStorage` interface and its S3 implementation for SeaweedFS: durable media, chunked uploads, signed links.
- `backend/app/services/storage/local.py` — working area of a running job on the media volume; PyAV and yt-dlp need local files.
- `backend/app/services/projects/projects.py` — project registration and the licence check (FR01).
- `backend/app/services/audit/audit.py` — adds entries to the append-only audit log (FR18).
- `backend/app/services/llm/` — LLM layer (`docs/llm-contract.md`, section 7): `provider.py` holds the `LLMProvider` interface with its request and reply types, `errors.py` the LLM errors, `client.py` the `LLMClient` (`complete_json`: schema validation, retries with feedback and one log line per call), `prompts.py` the prompt files and their versions, `ollama.py` and `openai_compatible.py` the two providers (the only files that import LangChain) and `factory.py` the provider chosen by configuration: the profiles in `backend/app/core/llm.toml` plus the `LLM_*` variables.
- `backend/app/services/workflow/ingestion_pipeline.py` — `run_ingestion`: runs FR02 steps 2–6 on local files, sends the results to object storage and reports each step as a job event.
- `backend/app/services/workflow/dispatcher.py` — `JobDispatcher` interface.
- `backend/app/services/workflow/rabbitmq.py` — exchanges, queues and `RabbitMQDispatcher`.
- `backend/app/services/workflow/event_consumer.py` — applies worker events in the API and publishes `media.ingested`.
- `backend/app/services/workflow/progress_hub.py` — hands job updates to the WebSocket clients of this API instance.
- `backend/app/services/workflow/sweeper.py` — periodic sweep: stalled jobs and abandoned uploads.
- `backend/app/services/workflow/{transitions,progress,state_machine}.py` — job status rules, progress weights and `apply_event` (T3.13).
- `backend/app/services/workflow/jobs.py` — creates jobs and applies status changes and worker events on the `jobs` table.
- `backend/app/services/workflow/ingestion_results.py` — reflects ingestion jobs on the project and media asset (FR02 steps 3 and 6).
- `backend/app/services/workflow/submission.py` — creates the media asset and job of an ingestion and hands it to the dispatcher.
- `backend/app/schemas/` — job contracts: enums, API and broker messages, timecodes. `clips.py` holds the clip generation formats shared by the LLM steps, validation and the clip proposal job (`docs/llm-contract.md`, section 6).
- `backend/app/core/exceptions.py` — domain exceptions of the job model.
- `backend/app/database/` — SQLAlchemy base, session (`get_db`) and `models/`.
- `backend/migrations/` — Alembic migrations; `alembic upgrade head` runs when the backend starts.
- `backend/app/workers/ingestion_worker.py` — RabbitMQ worker that runs the ingestion; it never touches PostgreSQL and runs from the backend image.
- `backend/app/auth`, `backend/app/services/users` — empty packages reserved for auth and users.
- `backend/tests/` — pytest tests; `conftest.py` puts the backend root on `sys.path`. `in_process_dispatcher.py` and `in_memory_object_storage.py` are stand-ins for the broker and SeaweedFS in API tests. `fake_llm_provider.py` replies with scripted LLM answers, so no test needs a model or network; `data/clips/short_transcript.json` is a synthetic transcript for the clip generation tests. `data/llm/prompts/` holds the prompt files of the LLM layer tests.
- `frontend/` — React 19 + TypeScript + Vite. Pages still use `src/data/mock.ts`, except sign-in:
  - `src/lib/api.ts` — `apiFetch`: calls the backend under `/api` with the session cookie (no tokens in the browser); a 401 goes to the login page.
  - `src/lib/auth.ts`, `src/lib/paths.ts` — sign-in, sign-up, sign-out and account deletion through the backend and Keycloak; frontend paths and the `next` check.
  - `src/auth/` — route loaders (`requireUser`, `redirectIfSignedIn`), `useCurrentUser` and the session check screens.
- `traefik/` — reverse proxy (T4.36): `dynamic/tls.yml` (TLS options and certificate), `generate-dev-cert.sh` (self-signed certificate in `traefik/certs/`, kept out of git).
- Configuration: `docker-compose.yml`, `docker-compose.override.yml` (development only: host ports on 127.0.0.1), `.env.example`, `backend/requirements.txt`, `backend/Dockerfile`, `frontend/package.json`, `frontend/.oxlintrc.json`, `frontend/tsconfig*.json`.
- Durable media lives in SeaweedFS (`S3_BUCKET`, the `seaweedfs_data` Docker volume), encrypted at rest. `/data/media` (`MEDIA_ROOT`, the `media_data` Docker volume) only holds the files of a running job.

## Commands

Stack: Traefik is the entry point (https://localhost for the frontend, https://localhost/api for the backend, https://media.localhost for signed media links, https://auth.localhost for Keycloak; README "Endereços"). In development `docker-compose.override.yml` also publishes on 127.0.0.1: frontend :5173, backend :8000, Postgres :5432, RabbitMQ AMQP :5672 and management UI :15672, SeaweedFS S3 API :8333, Keycloak admin :8080; plus the `ingestion-worker` service:
- `sh traefik/generate-dev-cert.sh` — once, before the first start: the self-signed certificate for HTTPS.
- `docker compose up --build` — start everything; backend and frontend hot-reload via bind mounts.
- `docker compose down -v` — stop and delete volumes (DB, RabbitMQ, media).

Backend tests run with pytest in a local venv (from `backend/`); pytest stays out of the Docker image:
- `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt` — `requirements-dev.txt` = `requirements.txt` + pytest
- `python -m pytest` — all tests; `python -m pytest tests/test_ingestion.py -k <name>` — single test
- Database tests use PostgreSQL only, never SQLite, on a separate `pei_test` database created automatically. Start the services first with `docker compose up -d postgres rabbitmq seaweedfs`; tests that need RabbitMQ or SeaweedFS are skipped when those are down. `TEST_DATABASE_URL`, `TEST_RABBITMQ_URL` and `TEST_S3_ENDPOINT_URL` override the defaults (`localhost`).
- In Docker (no local ffmpeg needed; the images must be rebuilt after requirements change): `docker compose build backend ingestion-worker`, then `docker compose run --rm -e TEST_DATABASE_URL=postgresql+psycopg2://pei:pei@postgres:5432/pei_test -e TEST_RABBITMQ_URL=amqp://pei:pei@rabbitmq:5672/ -e TEST_S3_ENDPOINT_URL=http://seaweedfs:8333 backend sh -c "pip install -q --root-user-action=ignore -r requirements-dev.txt && timeout 360 python -m pytest -q -p no:cacheprovider --ignore=tests/test_download.py"` — pytest is installed only in the throwaway container, not in the image.
- Run `tests/test_download.py` apart, with the same command and `timeout 240 python -m pytest -q -p no:cacheprovider tests/test_download.py`: a YouTube download can hang for a long time, and it would hold the whole suite.
- `tests/test_ingestion.py` uses synthetic files built by the `make_sample` fixture in `conftest.py` (no network); `tests/test_download.py` needs network and the `ffmpeg` executable.
- PyAV wheels bundle the FFmpeg libraries, so PyAV-based tests need nothing else on the host. Download tests need network and the `ffmpeg` executable on PATH (yt-dlp uses it to merge formats and cut ranges) and are skipped without it. Tests write to pytest temp dirs, not `/data/media`.
- `tests/test_llm_real.py` (marker `llm`) runs against a real model only when `TEST_LLM_PROFILE` is set, never in CI; see the README section "LLM (Ollama)" for the command.

Frontend (in `frontend/`):
- `npm run dev` — Vite dev server
- `npm run build` — `tsc -b` type-check + production build
- `npm run lint` — oxlint
- `npm run preview` — serve the production build

## Media processing (PyAV and yt-dlp)

Media is processed through Python libraries, never by calling the `ffmpeg`, `ffprobe` or `yt-dlp` executables with `subprocess`:
- **PyAV** (`av`) for inspection, integrity checks, decoding, audio resampling, waveform data, keyframe index and proxy encoding.
- **yt-dlp Python API** (`yt_dlp.YoutubeDL`) for remote probing (`extract_info(..., download=False)`) and downloads.
- The `ffmpeg` executable stays in the Docker image only because yt-dlp uses it internally (merging video + audio, cutting ranges).

Patterns:
- Open media with `with av.open(str(path)) as container:` so it is always closed; for outputs open with mode `"w"`.
- Work in a streaming way (packet/frame loops, resampler/encoder flushed at the end); never load a whole video or audio track into memory — sources can be 4 h long.
- Catch `av.FFmpegError` and re-raise as `RuntimeError` with a clear message; catch `yt_dlp.utils.DownloadError` the same way.
- Raise `FileNotFoundError` for missing inputs and `ValueError` for business-rule rejections (e.g. no audio stream).
- Create output parent directories first (`mkdir(parents=True, exist_ok=True)`) and return the output `Path`.
- Build yt-dlp options as a dict from `config.py` values; always set `noplaylist` and quiet output; user-supplied URLs are validated before they reach yt-dlp.
- These calls are blocking and CPU-heavy: run them only in workers, never in an endpoint.

## Code conventions

- Pipeline functions get a short banner comment above the docstring: one line on what it does and one `Source:` line citing the spec step (e.g. `MS2 FR02 – Step 4`) or other origin. Keep it to a few lines; the docstring holds the details.
- No hardcoded strings or numbers in code. Every value lives in `backend/app/core/config.py`: limits, timeouts, paths and directory/file names, URLs, formats and codecs, FFmpeg parameters (sample rate, resolution, CRF, bitrates), queue/exchange names, status values, error codes and user-facing messages. Values that can vary per environment are read from environment variables there, with the default next to them; fixed values are module-level constants in the same file. Code imports them from there.
- Exceptions (stay inline): names that belong to a library's interface (PyAV attributes and arguments, yt-dlp option keys such as `noplaylist`, `info_dict` keys such as `duration`), and test inputs inside tests. The values passed to them (codecs such as `libx264`, sample formats such as `s16`, rates, resolutions, CRF, presets) still live in `config.py`.
- Files in `backend/migrations/versions/` are a frozen history: they keep literal values and never import `config.py`.

## Working rules

- All code content in English: identifiers, comments, log and error messages, docstrings, tests.
- SupoClip (AGPL-3.0) is a design reference only. Never copy or adapt its code, not even small snippets; understand the approach, then write an original implementation. Only open SupoClip when the user explicitly gives its path.
- Do not run any git commands; the user handles version control.
- After each approved step is written, suggest one short commit message for it in Conventional Commits style, without Jira keys (e.g. `feat(llm): add LLM provider interface and errors`).
- Do not add new dependencies (pip, npm, Docker images) without asking first. Test-only Python packages go in `backend/requirements-dev.txt`, never in `requirements.txt`.
- Never read or print secrets (`.env` files, credentials, keys).
- Before adding or changing any code, always show the user the exact code first (full content of new files, the before/after of edited parts) and wait for explicit approval before writing it. This applies to every change, including single-file edits and approved plans: an approved plan does not approve the code.
- Work in small steps: propose a few files at a time, not a whole phase at once.
- After every task, report what was done and list every file changed.



# SynopStudio – Requirements

> Sources: MS2 Elaboration report (functional requirements, actors, user stories, use cases, non-functional requirements), project proposal, MS3 report §1 (legal requirements and Terms of Service).
> Requirements marked **(not yet specified)** have only a description in MS2; details are still to be defined.

## 1. Actors

| Actor | Description |
| --- | --- |
| Content Creator | Registered user. Uploads videos and context documents, configures and reviews clips, corrects transcripts, approves and exports. No editing experience assumed. |
| Viewer | No account. Opens a clip through a link shared by a Content Creator; cannot upload, edit or export. Access can be public or restricted to invited people. |
| Administrator | Manages accounts, configures privacy, copyright and moderation rules, consults audit logs. |
| External Platform | Social networks and video repositories connected through the documented API. |

## 2. Functional requirements

### Module 1 – Project management, licensing and source ingestion

**FR01 – Metadata, authorship and licensing registration** (UC01; US01, US02)
- Create a project with title, authorship, speakers, recording date, licence (Creative Commons, institutional permission, public debate broadcast rights) and copyright notice.
- Explicit confirmation of copyright ownership or usage authorisation before processing.
- Metadata permanently associated with the project for auditing.
- **Acceptance:** the AI pipeline cannot be triggered without a valid licence and authorship confirmation.

**FR02 – Multi-source long-form video ingestion** (UC02, UC03; US03–US07)
- Inputs: direct upload (MP4, MOV, MKV, WebM, AVI; H.264, H.265, VP9, AV1; AAC, MP3, Opus, PCM) or an authorised HTTP/HTTPS link (YouTube, Vimeo, institutional repositories); project ID; optional start/end timecodes.
- Upload: client checks extension and MIME type; chunked multipart upload for multi-GB files.
- Link: validate URL syntax, domain and accessibility; check duration against platform limits; fetch asynchronously up to 1080p. Link import only for videos the creator owns or is authorised to use (MS3 §1.3.2).
- Inspection (FFprobe in MS2; implemented with PyAV): headers, corrupted packets, variable frame rate, at least one audio track; silent or unreadable files rejected and project set to `Ingestion Failed` with details.
- Audio normalized to 16 kHz, 16-bit mono PCM WAV; waveform and volume profile.
- Proxy video (e.g. 720p H.264) and keyframe index.
- Technical metadata persisted (runtime, dimensions, aspect ratio, frame rate, sample rate, source URL or file name); broker event triggers transcription.
- Real-time progress notifications to the UI.
- **Acceptance:** MP4, MOV, MKV and WebM processed without corruption; a valid YouTube URL is staged without manual steps; ingestion runs asynchronously without blocking or timing out the UI; files without decodable audio and invalid URLs return descriptive errors.

**FR03 – Ingestion of authorised auxiliary context documents** (UC04; US08)
- Upload PDF, PPTX, DOCX or TXT (papers, slides, briefing notes, glossaries).
- Extract plain text, headings, speaker bios and acronyms; build a keyword and entity lexicon per project for speech recognition and LLM prompts.
- **Acceptance:** extracted text is indexed and available to the transcription refinement module.

### Module 2 – Multimodal processing and AI transcription

**FR04 – Synchronized audio transcription and time alignment** (UC05; US09)
- Sentence- and word-level timestamped transcript; default European Portuguese, architecture extensible to other languages.
- Inputs: normalized WAV; language parameter; acoustic context profile tag ("Academic Lecture", "Political Debate", "Conference", "Interview").
- Processing, outputs and acceptance criteria **(not yet specified)**.

**FR05 – Speaker identification and voice turn attribution** (UC05, UC06; US10, US11)
- Partition audio by speaker ("who spoke when"), including rapid turn-taking, similar voices and overlapping speech; speaker names can be corrected by the user. **(not yet specified)**

**FR06 – Terminology refinement using document context** (UC05; US12)
- Compare ambiguous or low-confidence words against the lexicon from FR03. **(not yet specified)**

### Module 3 – Semantic segmentation and natural-language search

**FR07 – Structural segmentation by topics, scenes and interventions** (UC07; US13) **(not yet specified)**

**FR08 – Natural-language semantic search** (UC08; US14)
- Search video, transcript and chapters by meaning, not exact keywords. **(not yet specified)**

### Module 4 – Intelligent clip proposal and synthesis

**FR09 – Summarization and output configuration** (UC09; US15)
- User sets target duration, thematic focus, audience and aspect ratio. **(not yet specified)**

**FR10 – Automated clip generation focused on rigor** (UC10; US16, US17)
- Clips prioritise rigor, coherence and completeness; engagement is secondary. Each proposal states why it was selected. **(not yet specified)**

**FR11 – Verifiable traceability and context-loss warnings** (UC11; US18, US19)
- Every clip keeps a verifiable link to its exact source intervals; warnings when discontinuous edits or omitted speech may change the speaker's meaning. **(not yet specified)**

### Module 5 – Workspace editing and human editorial control

**FR12 – Hybrid timeline and synchronized transcript editing** (UC12, UC13; US20, US21)
- Cut, trim, reorder and reject segments through the transcript or the timeline; preview. **(not yet specified)**

**FR13 – Visual confidence scoring** (UC11; US22)
- Highlight low-confidence words, speaker attributions and summaries. **(not yet specified)**

**FR14 – Automated visual reframing** (UC14; US23)
- 16:9 ↔ 9:16, keeping the active speaker or slide in frame. **(not yet specified)**

**FR15 – Explicit human approval and hallucination prevention** (UC15; US24, US25)
- No rendering/export without explicit approval; subtitles match speech verbatim; no fabricated quotes. **(not yet specified)**

### Module 6 – Textual synthesis, overlays and rendering

**FR16 – AI metadata generation with provenance tagging** (UC16; US26, US27)
- Suggested title, description and tags per approved clip, clearly marked as AI-generated. **(not yet specified)**

**FR17 – Rendering with effects and dynamic subtitles** (UC17; US28)
- Cuts, reframing, styled synchronized subtitles and effects (speaker lower thirds, zoom cuts, progress bars, word highlighting). **(not yet specified)**

### Module 7 – Export and editorial accountability

**FR18 – Audit logging and editorial decision tracking** (UC19, UC22; US30, US31)
- Immutable chronological log of every AI recommendation and every manual change. **(not yet specified)**

**FR19 – Export packaging and distribution** (UC18; US29)
- Social-media presets, batch archive download, separate subtitle files, publishing metadata. **(not yet specified)**

### User stories without a functional requirement

| Story | Description | Use case |
| --- | --- | --- |
| US32 | Viewer opens a clip link and sees the exact moment in the original recording. **Under review:** the team indicated that the source moment is for the creator, not the Viewer. | UC25 |
| US33 | Share a clip only with invited people. | UC20 |
| US34 | Delete a project and all its data. | UC21 |
| US35 | Administrator manages accounts and moderation rules. | UC23, UC24 |

## 3. Non-functional requirements

| Category | Requirement | Target |
| --- | --- | --- |
| Performance | Asynchronous processing of long videos | UI actions < 200 ms; job submission < 5 s |
| Performance | Automation of highlight detection, cutting, captioning, reframing | ≥ 80% less manual time; 1 h recording → clips in ≤ 15 min |
| Performance | Segment and speaker identification in long videos | Up to 4 h videos; ≤ 5 min per hour of footage |
| Performance | Configurable clip duration | 5–180 s (default 15–60 s) |
| Accuracy | Word-level timestamps | ±100 ms |
| Accuracy | Context files improve transcription | ≥ 20% relative WER improvement |
| Accuracy | Speaker identification | ≥ 90% for up to 6 speakers; manual correction possible |
| Accuracy | Clip traceability to source | ±100 ms |
| Accuracy | Faithful AI titles and descriptions | Zero fabricated quotes |
| Usability | Transcript-based editing | Seek < 300 ms; edits applied < 1 s |
| Usability | Natural-language search | Response < 2 s; ≥ 85% top-5 relevance |
| Usability | Explainable clip selection | Rationale for 100% of AI-proposed clips |
| Maintainability | Modular architecture | ≥ 5 independently deployable modules |
| Maintainability | Documented API | ≥ 95% of endpoints in OpenAPI 3.x |
| Maintainability | Swappable open LLMs | ≥ 2 providers via configuration only |
| Maintainability | Extensibility | New aspect ratio ≤ 1 day; new language ≤ 3 days |
| Security / ethics | Content integrity | 100% of clips traceable; zero altered quotes |
| Security / ethics | Secure handling of uploads | TLS 1.3 in transit; AES-256 at rest; licence confirmed on 100% of projects |
| Security / ethics | Transparency of AI decisions | Rationale and source references for 100% of AI decisions; audit logs kept ≥ 12 months |

## 4. Legal and compliance requirements (MS3)

| Requirement | Impact on the system | Source |
| --- | --- | --- |
| Personal data collected: first and last name and email (account), original videos and audio (processing), social network data (profile integration and performance score) | Store only these categories for these purposes | MS3 §1.1 |
| Minimum age 13; users aged 13–18 need parental authorisation | Registration flow | MS3 §1.4.1 |
| Licence and authorisation confirmed before processing; lectures by third parties need the lecturer's authorisation | FR01 validation | MS3 §1.3.2 |
| Link import only for videos the creator owns or is authorised to use | FR02 | MS3 §1.3.2 |
| AI-generated text labelled and marked in a machine-readable way (EU AI Act Art. 50); users may not remove AI labels or links to the original | FR16, export (C2PA under evaluation) | MS3 §1.3.1, §1.4.1 |
| Explicit human approval and audit log support the human-review exception for public-interest text | FR15, FR18 | MS3 §1.3.1 |
| Anyone can report a clip; content can be suspended pending review; removal decisions notified with reasons, appealable and logged (Digital Services Act) | Report endpoint, moderation workflow (UC24) | MS3 §1.3.2, §1.4.1 |
| Project and account deletion removes videos, documents, transcripts and clips; billing and licence/editorial audit records kept 12 months | Deletion service, retention policy | MS3 §1.4.3 |
| Export screen warns that paid promotion of a political clip is political advertising, and about electoral periods | Export flow | MS3 §1.3.3 |
| Subtitles exported as WebVTT | FR19 | MS3 §1.3.4 |
| Subscription plans with tokens (import, transcription, clip generation); 14-day refund if no tokens used | Billing/usage tracking **(scope to confirm)** | MS3 §1.4.3 |

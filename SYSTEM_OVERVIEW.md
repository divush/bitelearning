# BiteLearning — System Overview

A locally-run, single-user tool that turns a book (PDF) into a personalized, structured curriculum: an ordered set of short lessons — built from the book's actual content, tailored to how you like to learn, enriched with real external references, and tracked for completion. Everything runs on your own machine; nothing leaves it except calls to the OpenAI API (for generation) and DuckDuckGo (for lesson references).

This document has two parts: **Section 1** describes how the system behaves and what it does, for anyone reading who isn't going to touch the code. **Section 2 onward** is the technical reference — architecture, database schema, routes, and file layout.

---

## 1. How It Works (User Level)

### 1.1 Adding a book

You click **"Add a book"** in the sidebar, pick a PDF through your OS's native file picker, and optionally give it a cleaner title than the filename. The file is copied into the app's local storage (`data/books/`, renamed automatically if another book already has that filename) and parsed immediately — this step is fast (seconds, even for a 500-page book) because no AI model is involved yet.

### 1.2 Parsing & chapter breakdown

The PDF's raw text is extracted page by page, then the system figures out where chapters begin and end, trying three approaches in order until one works:

1. **Embedded outline/bookmarks** — most PDFs from real publishers have a navigable table of contents baked into the file. This is used first when present, since it's free and accurate.
2. **Heuristic detection** — if there's no usable outline, the system looks at font size/boldness across the document plus common phrasing ("Chapter 3", "CHAPTER ONE") to guess where new chapters start, while filtering out text that repeats on almost every page (running headers/footers, which would otherwise look like fake "chapters").
3. **Whole-book fallback** — if neither of the above finds anything usable, the entire PDF is treated as one chapter, so a book is never rejected outright — the result is just coarser.

Once chapters are known, each chapter's text is split into overlapping chunks (target size and overlap are configurable in `app/config.py` - `CHUNK_TARGET_TOKENS`/`CHUNK_OVERLAP_TOKENS`) — this is the unit later steps actually feed to the AI, since a whole book at once is too much even for large-context models to reason over precisely.

### 1.3 Chapter summarization

Before a curriculum can be planned, each chapter gets a short AI-written summary — aware of everything summarized so far, so it doesn't just describe the chapter in isolation but notes how it builds on what came before. This is what lets later steps be aware of the *whole* book without re-reading every chunk each time.

This now runs automatically as part of clicking **"Generate Plan"** (§1.4) — it's no longer a separate manual step. It's safe to run every time a plan is (re)generated: chapters that already have a summary are skipped, so an already-summarized book adds no real delay. `scripts/summarize_book.py` still exists for running it standalone if you want to.

### 1.4 Plan generation

Clicking **"Generate Plan"** on a book's page kicks off the curriculum-design step. Behind that one click, two things happen in order:
1. Any chapter that doesn't have a summary yet gets one first (§1.3) — the page shows a live progress bar ("Summarizing chapters… X of Y done") while this runs, if there's anything left to do.
2. Once all chapters are summarized, the actual planning call runs, considering: the chapter summaries (whole-book map), your **Learner Profile** (how you like to learn, in general), and that book's **Book Context** (why you're reading *this* book, what you already know, what to focus on or skip). The page switches to a spinner + elapsed-time counter for this part.

Front-matter chapters (cover, copyright, table of contents, part-dividers — anything with fewer than 8 chunks) are excluded from being turned into lessons themselves, but their titles are still shown to the model so it retains a sense of the book's real structure.

The result is an ordered list of lesson topics — a title and a short "what this covers and why it's here" blurb for each — matched to your stated depth/breadth/session-length/tone preferences. No lesson content is written yet; this is purely the table of contents for your personalized version of the book. Both steps run in the background; you don't need to stay on the page.

### 1.5 Lesson generation

Once a plan exists, **"Generate Lessons"** becomes available. For each lesson, in order, the system gives the model:
- That lesson's brief (title + what it should cover, from the plan)
- The actual book text for the chapter(s) it draws from
- The whole-book chapter summaries (context)
- A note on everything already explicitly covered by earlier lessons in this book (so lessons don't repeat each other)

The model can then decide, on its own judgment, whether searching the web would meaningfully enrich the lesson — real case studies, canonical papers, notable production incidents — and do so before writing anything final. It's not forced to search; if the book's own material is sufficient, it skips straight to writing.

Each finished lesson has three parts:
- **Core content** — a self-contained explanation, written so it's readable on its own days after the previous lesson (it restates enough context rather than assuming you remember everything).
- **References** — a short list of external links, each with a note on why it's relevant.
- **Exercises** — practice prompts where the material lends itself to that, with an optional hint (not a full answer key — there's no grading in this system, deliberately).

This runs in the background, one lesson at a time. The page shows a real progress bar (X of Y done), which lesson is currently being written, and marks any lesson that failed distinctly in the lesson list — so a failure doesn't silently look identical to "not started yet."

### 1.6 Reading & progress tracking

Click any lesson in the checklist to read it. **"Mark as completed"** toggles a simple done/not-done flag plus a timestamp — no grading or comprehension scoring (explicitly out of scope for this phase). The sidebar and each book's page show a running completion count (e.g. "6 of 11 lessons complete").

### 1.7 Learner Profile & Book Context

- **Learner Profile** (one, global, edited from the sidebar's "Learner profile" link): example-first vs. theory-first, session length preference, depth vs. breadth, tone, and free-form notes. Applied by default to every book.
- **Book Context** (one per book, edited from that book's "Edit book context" link): your goal for this specific book, prior familiarity, focus areas, and areas to skip. Refines/overrides the general profile for that one book.

Both are optional — if left blank, generation falls back to sensible generic defaults (moderate depth, mixed example/theory balance, broad coverage of the whole book).

---

## 2. Architecture

```
                         ┌───────────────────────────┐
                         │        Browser (UI)         │
                         │  Jinja2 templates + htmx     │
                         │  hand-written CSS (no build) │
                         └──────────────┬───────────────┘
                                        │ HTTP
                         ┌──────────────▼───────────────┐
                         │      app/web/  (FastAPI)       │
                         │  routes.py, templating.py       │
                         │  NEVER imports app.models/db/    │
                         │  generation/progress/ingestion   │
                         │  directly - services only        │
                         └──────────────┬───────────────┘
                                        │ calls
                         ┌──────────────▼───────────────┐
                         │   app/services/  (boundary)     │
                         │  book_service.py - the ONLY      │
                         │  layer allowed to import the      │
                         │  domain layer below. Returns       │
                         │  plain dataclasses (dto.py),        │
                         │  never live ORM objects.              │
                         └───┬───────┬───────┬───────┬────┘
                             │       │       │       │
              ┌──────────────▼┐ ┌────▼────┐ ┌▼───────────┐ ┌▼──────────┐
              │ app/ingestion/ │ │app/     │ │app/        │ │app/models │
              │ pdf_parser.py  │ │generation│ │progress.py │ │.py         │
              │ chaptering.py  │ │summarizer│ │mark done/  │ │SQLAlchemy  │
              │ chunking.py    │ │plan_gen  │ │not done    │ │ORM tables  │
              │ pipeline.py    │ │lesson_gen│ │            │ │            │
              └────────────────┘ └────┬─────┘ └────────────┘ └─────┬──────┘
                                       │ LangChain / LangGraph            │
                                ┌──────▼──────┐                    ┌──────▼──────┐
                                │app/tools/    │                    │   SQLite     │
                                │search.py      │                   │  (one file,  │
                                │(DuckDuckGo,    │                  │ data/        │
                                │ provider-      │                  │ bitelearning │
                                │ agnostic)       │                 │ .db)         │
                                └───────┬────────┘                 └──────────────┘
                                        │
                                ┌───────▼────────┐
                                │  OpenAI API      │
                                │  (gpt-4.1 family) │
                                └──────────────────┘
```

**Why the strict layering:** the web layer can be replaced (different framework, different frontend entirely) without touching a single line of generation or persistence logic, because it only ever talks to `book_service.py`'s plain-dataclass interface. This was a hard requirement, not a preference, and it's mechanically checked — the test suite includes a boundary check (`grep` over `app/web/` for any direct import of the domain modules) that fails the build if it's ever violated.

### 2.1 Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python | one runtime for ingestion, generation, storage, and UI |
| Web framework | FastAPI + Jinja2 + htmx | server-rendered, no SPA build step, htmx handles the few interactive bits (mark-complete, generation polling) |
| Persistence | SQLite via SQLAlchemy ORM | single file, zero config, plenty for "a handful of books in flight" |
| PDF parsing | PyMuPDF (`fitz`) | only library that gives text + outline + font metadata in one place |
| Generation | LangChain + LangGraph + OpenAI (`gpt-4.1`/`gpt-4.1-mini`) | LangGraph specifically for Lesson Generation's tool-calling loop; plain LangChain suffices for the two single-call steps (summarization, plan generation) |
| Search | DuckDuckGo, via `langchain-community` | free, no API key; wrapped behind a stable `web_search()` interface so the provider can be swapped later without touching the generation graph |
| Background jobs | FastAPI `BackgroundTasks` | no Celery/Redis — appropriate at single-user local scale; progress tracked via existing `status` columns, no separate job table |

### 2.2 Model usage by stage

| Stage | Model | Call shape |
|---|---|---|
| Chapter Summarization | `gpt-4.1-mini` | one call per chapter (rolling context of prior chapters' summaries); falls back to a batch map-reduce only if a single chapter's text exceeds ~950k tokens |
| Plan Generation | `gpt-4.1` | one call per book, structured output enforced via Pydantic schema |
| Lesson Generation — research | `gpt-4.1-mini` | agent loop, 0+ tool calls to `web_search`, capped by a recursion limit of 15 |
| Lesson Generation — compose | `gpt-4.1` | one final structured-output call per lesson, after research finishes |

---

## 3. Database

**Type:** SQLite, single file at `data/bitelearning.db`. No migrations tool — the schema is created via SQLAlchemy's `Base.metadata.create_all()` (`scripts/init_db.py`). Path is configurable via the `BITELEARNING_DB_PATH` environment variable (`.env`), defaulting to the path above.

**7 tables**, defined in `app/models.py`:

### `learner_profile` — singleton (always id=1)
```
id                              INTEGER  PRIMARY KEY
example_first_vs_theory_first   TEXT     nullable
session_length_pref             TEXT     nullable
depth_vs_breadth                TEXT     nullable
tone_pref                       TEXT     nullable
raw_notes                       TEXT     nullable
updated_at                      DATETIME
```
Cross-book. Applied by default to every generation call unless a book's own context overrides it.

### `books`
```
id                INTEGER   PRIMARY KEY
title             TEXT      NOT NULL   (defaults to filename stem unless overridden at upload)
source_filename   TEXT      NOT NULL
num_pages         INTEGER   nullable
status            TEXT      "uploaded" | "parsing" | "parsed" | "failed"
created_at        DATETIME
```
Has many `chapters`, one `book_contexts` row, many `plans` (in practice one active plan per book).

### `chapters`
```
id            INTEGER   PRIMARY KEY
book_id       INTEGER   FK -> books.id
order_index   INTEGER   (position within the book)
title         TEXT      NOT NULL
start_page    INTEGER   (0-based, inclusive)
end_page      INTEGER   (0-based, inclusive)
summary       TEXT      nullable  (filled in by the Chapter Summarization step)
```
Has many `chunks`.

### `chunks`
```
id            INTEGER   PRIMARY KEY
chapter_id    INTEGER   FK -> chapters.id
order_index   INTEGER   (position within the chapter)
token_count   INTEGER
text          TEXT      NOT NULL  (the actual source text fed to generation, ~900 tokens/chunk)
```

### `book_contexts` — one per book
```
id                  INTEGER   PRIMARY KEY
book_id             INTEGER   FK -> books.id, UNIQUE
goal                TEXT      nullable
prior_familiarity   TEXT      nullable
focus_areas         TEXT      nullable
skip_areas          TEXT      nullable
updated_at          DATETIME
```

### `plans`
```
id           INTEGER    PRIMARY KEY
book_id      INTEGER    FK -> books.id
status       TEXT       "generating" | "complete" | "failed"
created_at   DATETIME   (also doubles as "generation started at" - the row is
                          created with status="generating" and committed
                          *before* the AI call, so it's visible to a concurrent
                          reader/poller while work is in progress)
```
Has many `lessons`.

### `lessons` — one row per planned/generated lesson
```
id                     INTEGER    PRIMARY KEY
plan_id                INTEGER    FK -> plans.id
book_id                INTEGER    FK -> books.id   (denormalized, avoids a join through plans)
order_index            INTEGER    (position within the plan)
title                  TEXT       NOT NULL
topic_summary          TEXT       nullable   (written at plan time)
content                TEXT       nullable   (markdown, written at lesson-generation time)
external_references    TEXT       nullable   (JSON list of {title, url, why_relevant})
exercises              TEXT       nullable   (JSON list of {prompt, guidance})
source_chapter_ids     TEXT       nullable   (JSON list[int] - which chapters this lesson draws from)
status                 TEXT       "planned" | "generating" | "generated" | "failed"
is_complete            BOOLEAN    default False
completed_at           DATETIME   nullable
created_at             DATETIME
```
**Design note:** the requirements originally called for a separate "Progress Record" concept, but since completion state is strictly 1:1 with a lesson (never more than one record, no independent lifecycle), `is_complete`/`completed_at` were folded directly onto `Lesson` instead of a separate table — same data, one less join.

### Relationships at a glance
```
learner_profile                (singleton, not FK'd - applied globally)

books ──1:1── book_contexts
books ──1:N── chapters ──1:N── chunks
books ──1:N── plans ──1:N── lessons
```
All child rows cascade-delete with their parent at the ORM level (`cascade="all, delete-orphan"`) — deleting a `Book` removes its chapters, chunks, plan, and lessons in one call.

---

## 4. The Web Layer

### 4.1 Routes

| Method & path | Purpose |
|---|---|
| `GET /` | Redirects to the first book's plan page, or an empty-library message if none exist |
| `GET /books/new` / `POST /books` | Add-a-book form / handles the upload, saves to `data/books/`, ingests, redirects to the new book |
| `GET /profile` / `POST /profile` | Learner Profile form / save |
| `GET /books/{book_id}` | A book's plan page - progress bar, generation status, lesson checklist |
| `GET /books/{book_id}/context` / `POST /books/{book_id}/context` | Book Context form / save |
| `GET /books/{book_id}/status` | Returns just the generation-status fragment, polled by htmx every 3s while a plan/lessons run is in progress |
| `POST /books/{book_id}/plan` | Kicks off Plan Generation as a background task, redirects back immediately |
| `POST /books/{book_id}/lessons/generate` | Kicks off Lesson Generation (all remaining lessons) as a background task |
| `GET /books/{book_id}/lessons/{order_index}` | The lesson reader |
| `POST /books/{book_id}/lessons/{order_index}/complete` / `.../incomplete` | Toggle completion, htmx returns just the updated button |

### 4.2 Background generation & live progress

Plan/Lesson generation run via FastAPI's `BackgroundTasks` — the HTTP request returns immediately (redirect), and the actual work continues in a worker thread. There's no separate job-tracking table; the existing `Plan.status`/`Lesson.status`/`Chapter.summary` fields are the single source of truth, and they're written *before* the slow work starts (not just after), which is what makes live polling meaningful:
- Summarization (as part of "Generate Plan"): `book_service.start_plan_generation` drives `summarize_book` to completion before calling `generate_plan` - safe to call unconditionally, since chapters that already have a summary are skipped. Progress is derived, not stored separately: `chapters_total`/`chapters_summarized` in `BookWorkspace` are computed from existing chapter/chunk data (chapters with `chunk_count > 0`, and how many of those have `summary is not None`), giving a "Summarizing chapters… X of Y" progress bar with zero schema changes.
- Plan Generation: the `Plan` row is created with `status="generating"` and committed before the LLM call, so `created_at` doubles as a reliable "started at" timestamp for the elapsed-time counter shown in the UI once summarization is done.
- Lesson Generation: each `Lesson.status` flips to `"generating"` and commits immediately before that lesson's generation call, so the UI can show a progress bar, name the lesson currently in flight, and give any lesson that failed a distinct visual marker in the checklist (rather than looking identical to "not started").

**Known gap:** background tasks are in-process and don't survive a server restart. If the server is stopped/crashes mid-generation, whatever lesson was "generating" at that moment stays stuck in that status with nothing actively working on it — the fix so far has been a manual reset (flip that one lesson back to `"planned"` directly in the DB), after which re-triggering "Generate Lessons" picks up cleanly since the skip-logic only skips lessons already `"generated"`.

### 4.3 Templates
```
app/web/templates/
  base.html               - sidebar (library list, add-book, profile link) + content block
  plan.html               - a book's plan/checklist page
  reader.html             - the lesson reader
  profile.html            - Learner Profile form
  book_context.html       - Book Context form
  new_book.html           - add-a-book form
  empty_library.html      - shown when no books exist yet
  _generation_status.html - self-polling htmx partial (plan/lesson generation progress)
  _complete_button.html   - the mark-complete/incomplete button, reused in full renders and htmx swaps
```
Styling is a single hand-written stylesheet (`app/web/static/styles.css`) — a warm paper/ink palette with a brass accent for progress/interactive state and a separate moss-green for the "done" semantic state, a literary serif for titles/reading text, and a plain system-sans for UI chrome. No CSS framework — a full design system already existed (locked via an Artifact mockup reviewed before building) by the time the real templates were written, so introducing one would have fought it rather than helped.

---

## 5. File Layout
```
BiteLearning/
  app/
    config.py              - env-based settings, model names, chunk/threshold constants
    db.py                  - SQLAlchemy engine/session
    models.py               - the 7 ORM tables
    llm.py                   - chat-model factory (single place every generation module pulls from)
    progress.py               - mark complete/incomplete, progress summary
    ingestion/
      pdf_parser.py            - PyMuPDF text/outline/font extraction
      chaptering.py             - 3-tier chapter boundary detection
      chunking.py                - token-budgeted sub-chunking
      pipeline.py                  - ties parsing -> chaptering -> chunking -> persistence together
    generation/
      profile_context_format.py    - shared prompt formatting for Profile/Context
      summarizer.py                  - Chapter Summarization
      plan_generator.py                - Plan Generation
      lesson_generator.py                - Lesson Generation (LangGraph)
    tools/
      search.py                        - provider-agnostic web_search tool
    services/
      dto.py                             - plain dataclasses returned to the web layer
      session.py                          - FastAPI DB-session dependency
      book_service.py                       - the model-UI separation boundary
    web/
      app.py, routes.py, templating.py       - FastAPI app + routes + Jinja2 setup
      templates/                                - see §4.3
      static/styles.css                            - the whole design system
  scripts/                                          - see §6
  tests/                                              - one test file per module, all offline (stub models/tools, in-memory SQLite, zero real API calls)
  data/
    bitelearning.db          - the SQLite file (gitignored)
    books/                     - uploaded/ingested PDFs (gitignored)
  requirements.txt
  start.sh                      - convenience wrapper around scripts/run_web.py
```

---

## 6. Scripts Reference

Everything the UI can't do yet (see §7) is still available as a CLI script:

| Script | Purpose |
|---|---|
| `init_db.py` | Create all tables (idempotent) |
| `ingest_book.py <pdf> ["title"]` | Parse + chapter-detect + chunk a PDF, print a report |
| `summarize_book.py <book_id> [--force]` | Generate rolling chapter summaries |
| `set_learner_profile.py [--flags]` | Set/update the global Learner Profile (CLI: only touches flags passed) |
| `set_book_context.py <book_id> [--flags]` | Set/update a book's context (same partial-update semantics) |
| `generate_plan.py <book_id> [--force]` | Run Plan Generation |
| `generate_lessons.py <book_id> [--force] [--lesson-index N]` | Run Lesson Generation for the whole book or one lesson |
| `mark_lesson.py <book_id> <lesson_index> [--undo]` | Mark a lesson complete/incomplete |
| `show_progress.py <book_id>` | Print a completion checklist for a book |
| `run_web.py [--port] [--host]` | Start the web UI (also via `./start.sh`) |

---

## 7. Known Limitations / Deferred Work

- **No async job queue beyond in-process `BackgroundTasks`** — sufficient at single-user scale, but a job doesn't survive a server restart (see §4.2's known gap).
- **Add Book / ingestion is wired into the UI; Plan/Lesson generation triggers are wired in; but there's no "regenerate this one lesson" button in the UI yet** (the underlying `--lesson-index` capability exists in the script).
- **Book titles default to the PDF filename** unless a title is given at upload time — can look messy for awkwardly-named source files.
- **No understanding/comprehension checks, no "chat with the book"** — explicitly out of scope for this phase per the original requirements, but the schema was deliberately built to not block them later: `source_chapter_ids` traces every lesson back to its originating chapters/chunks, which is exactly the grounding a future chat-with-book feature would need.
- **No grading or spaced-repetition scheduling** — deliberately out of scope; progress tracking is binary (done/not-done) with a timestamp, nothing more.

---

## 8. Running It

```bash
cd ~/Desktop/BiteLearning
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env   # then fill in OPENAI_API_KEY
python scripts/init_db.py
./start.sh              # or: python scripts/run_web.py [--port 8000]
```
Then open `http://127.0.0.1:8000`. Run `python -m pytest tests/` to run the full test suite (offline, no API calls, no real cost).

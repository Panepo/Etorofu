# Etorofu Research Hub

An automated web research system that uses a multi-agent pipeline to search the web, write, and edit structured reports — all running locally with no external AI APIs.

## How It Works

1. A research topic is submitted via the API (or scheduled via cron)
2. The job enters an `asyncio.Queue` — one job runs at a time to respect VRAM limits
3. Three CrewAI agents run sequentially:
   - **Researcher** — searches DuckDuckGo and compiles facts (fast model)
   - **Writer** — drafts a structured Markdown report (smart model)
   - **Editor** — proofreads and polishes the report (smart model)
4. A tag generator extracts keywords from the finished report
5. The report and tags are persisted to SQLite

All reports are written in **Traditional Chinese (繁體中文)**.

## Tech Stack

| Component | Technology |
|---|---|
| API server | FastAPI (async) + Uvicorn |
| Agent framework | CrewAI |
| LLM engine | Ollama (local) |
| Research model | `qwen3.5:9b` |
| Writing / editing model | `qwen3.5:35b` |
| Search | DuckDuckGo (`langchain_community`) |
| Database | SQLite via SQLAlchemy async + aiosqlite |
| Config | `.env` via python-dotenv |

## File Structure

```
server.py           — FastAPI app, lifespan, background worker, all API endpoints
agent.py            — CrewAI agents and run_knowledge_extraction()
database.py         — SQLAlchemy models and all CRUD functions
cron.py             — Standalone script for scheduled report generation
install_dependency.py — Dependency installer helper
requirements.txt    — Python dependencies
Dockerfile          — Multi-stage Docker build
research_data.db    — SQLite database (created on first run, git-ignored)
```

## Setup

### Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com/) running with `qwen3.5:9b` and `qwen3.5:35b` pulled

### Install

```bash
pip install -r requirements.txt
```

### Configure

Create a `.env` file in the project root:

```env
OLLAMA_URL=http://localhost:8088
OLLAMA_MODEL_FAST=qwen3.5:9b
OLLAMA_MODEL_SMART=qwen3.5:35b
DATABASE_URL=sqlite+aiosqlite:///./research_data.db

# Optional — enable the built-in daily cron daemon
CRON_TOPIC=Latest developments in quantum computing
CRON_SCHEDULE=08:00
```

### Start the server

```bash
uvicorn server:app --host 0.0.0.0 --port 8050
```

Interactive API docs are available at `http://localhost:8050/docs`.

## API Reference

### Submit a research task

```
POST /research
Content-Type: application/json

{ "topic": "Advances in fusion energy 2025" }
```

Returns a `task_id`. Also accepts `application/x-www-form-urlencoded`.

### Poll task status

```
GET /status/{task_id}
```

Possible `status` values: `queued` → `searching` → `writing` → `tagging` → `completed` / `failed`

### List all reports

```
GET /reports
```

Returns summary objects: `id`, `topic`, `tags`, `created_at`. Does not include full content.

### Get a single report

```
GET /reports/{report_id}
```

### Edit a report

```
PATCH /reports/{report_id}
Content-Type: application/json

{ "content": "...", "tags": "tag1, tag2" }
```

At least one field (`content` or `tags`) must be provided.

## Scheduled Reports (Cron)

Two modes are available:

**Built-in daemon** — set `CRON_TOPIC` and `CRON_SCHEDULE` in `.env`. The server automatically queues one report per day at the configured time.

**External scheduler** — run `cron.py` directly via Windows Task Scheduler or crontab:

```bash
python cron.py
```

This reads `CRON_TOPIC` from `.env`, generates one report, saves it to the database, and exits.

## Docker

```bash
# Build
docker build -t etorofu .

# Run (mount a volume so the database persists)
docker run -d \
  --name etorofu \
  -p 8050:8050 \
  -v etorofu_data:/data \
  --env-file .env \
  etorofu
```

The default `OLLAMA_URL` inside the container points to `http://host.docker.internal:8088`. Override this in `.env` if your Ollama host differs.

## Architecture Notes

**Single-worker queue** — only one CrewAI `Crew` runs at a time. This is intentional: the target hardware (Asus GX10) has limited VRAM, and concurrent runs would cause out-of-memory errors.

**Sync/async boundary** — `Crew.kickoff()` is synchronous. It is always wrapped in `loop.run_in_executor(None, ...)` so it does not block the FastAPI event loop.

# Etorofu Research Hub

An automated web research system that uses a multi-agent pipeline to search the web, write, and edit structured reports through an OpenAI-compatible LLM server.

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
| LLM engine | OpenAI-compatible server (configured via `.env`) |
| Model | `CHAT_MODEL` |
| Search | DuckDuckGo (`langchain_community`) |
| Database | SQLite via SQLAlchemy async + aiosqlite |
| Config | `.env` via python-dotenv |

## File Structure

```
server.py           — FastAPI app, lifespan, background worker, all API endpoints
pyproject.toml      — Poe tasks, including the development server
agent.py            — CrewAI agents and run_knowledge_extraction()
database.py         — SQLAlchemy models and all CRUD functions
cron.py             — Queue all scheduled topics once via the running server
install_dependency.py — Dependency installer helper
requirements.txt    — Python dependencies
requirements-dev.txt — Development dependencies
Dockerfile          — Multi-stage Docker build
static/index.html   — Single-page web UI (list, add, edit, delete reports)
static/cron.html    — Manage recurring research topics
research_data.db    — SQLite database (created on first run, git-ignored)
```

## Setup

### Prerequisites

- Python 3.12+
- An OpenAI-compatible chat-completions server accessible at `CHAT_BASE_URL`

### Install

```bash
pip install -r requirements-dev.txt
```

### Configure

Create a `.env` file in the project root:

```env
CHAT_MODEL=your-model-name
CHAT_BASE_URL=http://localhost:8000/v1
CHAT_API_KEY=your-api-key
DATABASE_URL=sqlite+aiosqlite:///./research_data.db
SHIRATSUYU_BASE_URL=https://your-shiratsuyu-api
```

`SHIRATSUYU_BASE_URL` is the API base URL before `/auth`. Users sign in with
their Shiratsuyu email and password; their JWT is kept in an HttpOnly,
SameSite=Strict session cookie and verified with Shiratsuyu on every protected
request. Logging out removes the browser cookie; the JWT remains valid until
Shiratsuyu expires or revokes it. Expose both Etorofu and Shiratsuyu over HTTPS
to protect credentials and tokens in transit. When behind a TLS-terminating
proxy, configure Uvicorn to trust forwarded headers only from that proxy so
the session cookie is marked Secure.

### Start the server

```bash
poe dev
```

The web UI is available at `http://localhost:8050/`.
Interactive API docs are available at `http://localhost:8050/docs`.

## API Reference

All site pages and API endpoints except `/login`, `POST /auth/login`, and
`POST /auth/logout` require a valid Shiratsuyu session. API clients can instead
send `Authorization: Bearer <shiratsuyu_jwt>`. A failed or expired session
returns 401; an unavailable authentication service fails closed.

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

### Delete a report

```
DELETE /reports/{report_id}
```

## Scheduled Reports

Open **Scheduled Topics** in the web UI to add, edit, or delete recurring research topics. Each schedule has a starting date, a time, and an interval in days (1 for daily, 2 for every other day, 7 for weekly). Times are in the server's local time. If the starting date and time have passed, the first run is the next occurrence in that sequence.

The server checks schedules every 10 seconds and queues due topics through the same single-worker queue as manual research. Schedules persist in SQLite and take effect without restarting the server. If the server was stopped at a scheduled time, it queues one catch-up run on startup and advances to the next future occurrence; it does not queue every missed run. Like manual tasks, queued runs are in memory and do not survive a server crash or restart. Run only one server worker to preserve the single research queue.

The old `CRON_TOPIC` and `CRON_SCHEDULE` environment variables are no longer used. Add the desired topics in the web UI instead. To manually queue every configured topic once, run this while the server is running:

```bash
python cron.py
```

This submits jobs to the server and exits without waiting for reports. Set
`SHIRATSUYU_TOKEN` to a valid Shiratsuyu JWT for this manual command. The
server's built-in scheduler does not need a token. `python cron.py --daemon`
is no longer needed: scheduling runs in the server.

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

Set `CHAT_MODEL`, `CHAT_BASE_URL`, and `CHAT_API_KEY` in `.env`; they are passed to the container by `--env-file .env`.

### Deployed site

The site Compose and Nginx configuration in `D:\server\gx10-petallia` serves
Etorofu at `https://swai.getac.com.tw/etorofu/`. It builds from this checkout,
uses the site's `CHAT_MODEL`, `CHAT_BASE_URL`, `CHAT_API_KEY`, and
`SHIRATSUYU_BASE_URL` settings, and stores SQLite data in the `etorofu_data`
Docker volume. These URLs must be reachable from the container; `localhost`
refers to the container itself. Scheduled topics run in Taiwan time (UTC+8).

From the site configuration directory, deploy the changes with:

```bash
docker compose up -d --build etorofu
docker compose exec nginx nginx -t
docker compose up -d --no-deps nginx
```

The dedicated `etorofu_proxy` network gives Nginx the trusted address
`172.30.245.2` and Etorofu `172.30.245.3`, so Uvicorn accepts forwarded HTTPS
headers only from Nginx. If its subnet conflicts with an existing network,
update both addresses, Uvicorn's `--forwarded-allow-ips`, and Nginx's upstream
address together.

## Architecture Notes

**Single-worker queue** — only one CrewAI `Crew` runs at a time. This is intentional: the target hardware (Asus GX10) has limited VRAM, and concurrent runs would cause out-of-memory errors.

**Sync/async boundary** — `Crew.kickoff()` is synchronous. It is always wrapped in `loop.run_in_executor(None, ...)` so it does not block the FastAPI event loop.

## Project Overview
An automated web research system running on an Asus GX10. It uses **FastAPI** as the backend, **CrewAI** as the multi-agent framework, and **Ollama** to run local **Qwen 3.5** models. The system features an async task queue and SQLite persistent storage.

## Tech Stack
- **Framework**: FastAPI (async)
- **Agent Framework**: CrewAI
- **LLM Engine**: Ollama — `qwen3.5:9b` for research, `qwen3.5:35b` for writing/editing
- **Database**: SQLite via SQLAlchemy (async) + aiosqlite
- **Search Tool**: DuckDuckGo (`langchain_community.tools.DuckDuckGoSearchRun`)
- **Config**: `.env` loaded via `python-dotenv`

## File Structure
```
server.py       — FastAPI app, lifespan, background worker, API endpoints
agent.py        — CrewAI agent definitions and run_knowledge_extraction()
database.py     — SQLAlchemy models, init_db(), get_db(), and all CRUD functions
.env            — OLLAMA_URL, MODEL_FAST, MODEL_SMART
research_data.db — SQLite database file (git-ignored)
```

## Essential Commands
- **Start server**: `python server.py` or `uvicorn server:app --reload`
- **Install dependencies**: `pip install fastapi uvicorn crewai langchain_ollama langchain_community sqlalchemy aiosqlite duckduckgo-search python-dotenv`
- **API docs**: `http://localhost:8050/docs` after server start

## Code Conventions

### Language
- All CrewAI agent `role`, `goal`, `backstory`, and task `description` fields must be written in **Traditional Chinese (繁體中文)**.
- All research outputs and reports produced by agents must be in Traditional Chinese.
- Code comments, variable names, and this file are in English.

### Async Rules
- All database operations (`database.py`) must use `async/await` with SQLAlchemy's async engine.
- All CrewAI `Crew.kickoff()` calls are synchronous and **must** be wrapped in `loop.run_in_executor(None, ...)` to avoid blocking the FastAPI event loop.

### Naming
- Variables and functions: `snake_case`
- Classes and models: `PascalCase`

### FastAPI Patterns
- Use the `lifespan` context manager (via `@asynccontextmanager`) instead of the deprecated `@app.on_event("startup")`.
- Use `Depends(get_db)` for injecting database sessions into route handlers.
- Route handlers should delegate business logic to `agent.py` and `database.py` — keep `server.py` thin.

### Model Assignment
| Agent | Model env var | Purpose |
|---|---|---|
| Researcher | `MODEL_FAST` (`qwen3.5:9b`) | Web search — fast iteration |
| Writer | `MODEL_SMART` (`qwen3.5:35b`) | Draft generation — quality output |
| Editor | `MODEL_SMART` (`qwen3.5:35b`) | Proofreading — precision |
| Tag generator | `MODEL_FAST` (`qwen3.5:9b`) | Keyword extraction — via `generate_tags()` in `agent.py` |

## Architecture Notes

### Task Queue
All research jobs go through a single `asyncio.Queue`. Only one CrewAI `Crew` instance runs at a time. This is intentional — the GX10 has limited VRAM and running concurrent Crew instances will cause OOM errors. **Do not remove or bypass the queue.**

### Task Lifecycle
```
queued → searching → writing → tagging → completed
                                        ↘ failed
```
Task state is tracked in `tasks_db` (in-memory dict) in `server.py`. On completion, the result and generated tags are persisted to SQLite via `database.save_report()`.

### Database CRUD (`database.py`)

**`ReportModel` schema**: `id`, `topic`, `content`, `tags` (comma-separated, nullable), `created_at`

| Function | Description |
|---|---|
| `init_db()` | Create tables on startup |
| `get_db()` | FastAPI `Depends()` session provider |
| `save_report(task_id, topic, content, tags)` | Insert a completed report with tags |
| `load_report(report_id)` | Fetch one report by ID, returns `None` if missing |
| `load_all_reports()` | Fetch all reports as summary dicts (id, topic, tags, created_at) |
| `update_report(report_id, content)` | Update content, returns `bool` |
| `update_tags(report_id, tags)` | Update tags for an existing report, returns `bool` |
| `delete_report(report_id)` | Delete by ID, returns `bool` |

## Important Warnings
- **Never run multiple Crew instances concurrently.** The queue enforces this — do not change it.
- **Schema changes to `ReportModel`** require either a migration or deleting `research_data.db` to recreate it.
- `MODEL_FAST` and `MODEL_SMART` must be set in `.env` before starting the server. The app will not raise a clear error if they are missing — the Ollama call will simply fail at runtime.


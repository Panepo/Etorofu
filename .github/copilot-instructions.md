# Copilot Instructions — Etorofu

## Project Overview
An automated web research system running on an Asus GX10. It uses **FastAPI** as the backend, **CrewAI** as the multi-agent framework, and **Ollama** to run local **Qwen 3.5** models. The system features an async task queue and SQLite persistent storage.

## Tech Stack
- **Framework**: FastAPI (async)
- **Agent Framework**: CrewAI
- **LLM Engine**: Ollama — `qwen3.5:9b` for research, `qwen3.5:35b` for writing/editing
- **Database**: SQLite via SQLAlchemy (async) + aiosqlite
- **Search Tool**: DuckDuckGo (`langchain_community.tools.DuckDuckGoSearchRun`)
- **Config**: `.env` loaded via `python-dotenv`
- **Other details**: See `.github/reference/structure.md` for file structure and essential commands.

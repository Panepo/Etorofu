# Copilot Instructions — Etorofu

## Project Overview
An automated web research system running on an Asus GX10. It uses **FastAPI** as the backend, **CrewAI** as the multi-agent framework, and an **OpenAI-compatible LLM server** configured through `.env`. The system features an async task queue and SQLite persistent storage.

## Tech Stack
- **Framework**: FastAPI (async)
- **Agent Framework**: CrewAI
- **LLM Engine**: OpenAI-compatible server — `CHAT_MODEL`, `CHAT_BASE_URL`, and `CHAT_API_KEY` are configured in `.env`
- **Database**: SQLite via SQLAlchemy (async) + aiosqlite
- **Search Tool**: DuckDuckGo (`langchain_community.tools.DuckDuckGoSearchRun`)
- **Config**: `.env` loaded via `python-dotenv`
- **Other details**: See `.github/reference/structure.md` for file structure and essential commands.

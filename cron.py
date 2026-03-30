"""
cron.py — Daily scheduled report generator.

Reads CRON_TOPIC from .env and submits one research report per run.
Schedule this script externally (e.g. Windows Task Scheduler or crontab):

    python cron.py

Example .env entries:
    CRON_TOPIC=Latest developments in quantum computing
    CRON_SCHEDULE=08:00   # optional — used only if running in --daemon mode
"""

import asyncio
import os
import time
import uuid
import argparse
from dotenv import load_dotenv

from agent import run_knowledge_extraction
from database import init_db, save_report

load_dotenv()


def _run_task(task_id: str, topic: str) -> dict:
    """Run the CrewAI extraction in the current thread and return tasks_db entry."""
    tasks_db: dict = {}
    tasks_db[task_id] = {
        "id": task_id,
        "topic": topic,
        "status": "queued",
        "created_at": time.time(),
        "result": None,
    }
    run_knowledge_extraction(task_id, topic, tasks_db)
    return tasks_db[task_id]


async def generate_report(topic: str) -> str:
    """Generate a research report for *topic* and persist it to SQLite."""
    await init_db()

    task_id = str(uuid.uuid4())
    print(f"[cron] Starting report — task_id={task_id}  topic={topic!r}")

    loop = asyncio.get_event_loop()
    task_data = await loop.run_in_executor(None, _run_task, task_id, topic)

    if task_data.get("status") == "completed":
        await save_report(
            task_id=task_id,
            topic=topic,
            content=task_data.get("result", ""),
            tags=task_data.get("tags", ""),
        )
        print(f"[cron] Report saved  — task_id={task_id}")
    else:
        error = task_data.get("error", "unknown error")
        print(f"[cron] Report FAILED — task_id={task_id}  error={error}")

    return task_id


async def daemon(topic: str, schedule_time: str) -> None:
    """Run generate_report once a day at *schedule_time* (HH:MM, 24-hour)."""
    import datetime

    print(f"[cron] Daemon started — will generate report for {topic!r} every day at {schedule_time}")
    while True:
        now = datetime.datetime.now()
        target_h, target_m = map(int, schedule_time.split(":"))
        next_run = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
        if next_run <= now:
            next_run += datetime.timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()
        print(f"[cron] Next run at {next_run.strftime('%Y-%m-%d %H:%M')} "
              f"(in {wait_seconds / 3600:.1f} h)")
        await asyncio.sleep(wait_seconds)
        await generate_report(topic)


def main() -> None:
    parser = argparse.ArgumentParser(description="Etorofu daily report generator")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Keep running and trigger the report at CRON_SCHEDULE time each day.",
    )
    args = parser.parse_args()

    topic: str = os.getenv("CRON_TOPIC", "").strip()
    if not topic:
        raise SystemExit(
            "[cron] ERROR: CRON_TOPIC is not set in .env. "
            "Add a line like:  CRON_TOPIC=Your daily research subject"
        )

    if args.daemon:
        schedule_time: str = os.getenv("CRON_SCHEDULE", "08:00").strip()
        asyncio.run(daemon(topic, schedule_time))
    else:
        asyncio.run(generate_report(topic))


if __name__ == "__main__":
    main()

"""Queue all configured scheduled topics once through the running server."""

import argparse
import asyncio
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from database import init_db, list_scheduled_topics


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8050", help="Running Etorofu server URL")
    parser.add_argument("--daemon", action="store_true", help="Deprecated: scheduling is built into the server")
    args = parser.parse_args()
    if args.daemon:
        parser.error("The server now runs the scheduler; configure schedules on the Scheduled Topics page.")

    await init_db()
    jobs = await list_scheduled_topics()
    if not jobs:
        print("No scheduled topics configured.")
        return
    token = os.getenv("SHIRATSUYU_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set SHIRATSUYU_TOKEN to a valid Shiratsuyu JWT before queueing topics.")
    for job in jobs:
        request = Request(
            args.url.rstrip("/") + "/research",
            data=json.dumps({"topic": job["topic"], "details": job["details"]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SystemExit(f"Could not queue scheduled topic {job['id']}: {exc}") from exc
        print(f"Queued {job['topic']!r}: {result['task_id']}")


if __name__ == "__main__":
    asyncio.run(main())

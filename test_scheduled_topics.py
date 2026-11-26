import asyncio
import io
import json
import unittest
from datetime import date, datetime, time
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import database
import cron
import server


class ScheduledTopicsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(database.Base.metadata.create_all)
        self.session_patch = patch.object(
            database, "async_session", async_sessionmaker(self.engine, expire_on_commit=False)
        )
        self.session_patch.start()
        self.auth_patch = patch.object(server, "verify_shiratsuyu_token", new_callable=AsyncMock)
        self.auth_patch.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
            headers={"Authorization": "Bearer test-token"},
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.auth_patch.stop()
        self.session_patch.stop()
        await self.engine.dispose()

    def test_next_run_respects_calendar_interval_and_boundary(self):
        start = date(2026, 11, 1)
        self.assertEqual(
            database.next_scheduled_run(start, time(23), 2, datetime(2026, 11, 4, 10)),
            datetime(2026, 11, 5, 23),
        )
        self.assertEqual(
            database.next_scheduled_run(start, time(23), 7, datetime(2026, 11, 8, 23)),
            datetime(2026, 11, 15, 23),
        )
        self.assertEqual(
            database.next_scheduled_run(start, time(23), 1, datetime(2026, 10, 31)),
            datetime(2026, 11, 1, 23),
        )

    async def test_schedule_api_create_edit_delete_and_validate(self):
        payload = {
            "topic": "  AI research  ", "start_date": "2099-01-01",
            "schedule_time": "23:00", "interval_days": 2, "details": "  Focus on evidence  ",
        }
        response = await self.client.post("/scheduled-topics", json=payload)
        self.assertEqual(response.status_code, 201)
        job = response.json()
        self.assertEqual(job["topic"], "AI research")
        self.assertEqual(job["details"], "Focus on evidence")
        self.assertEqual(job["next_run"], "2099-01-01T23:00")
        self.assertEqual((await self.client.get("/scheduled-topics")).json(), [job])

        payload.update(topic="Space", interval_days=7, details="New focus")
        edited = await self.client.put(f"/scheduled-topics/{job['id']}", json=payload)
        self.assertEqual(edited.json()["interval_days"], 7)
        self.assertEqual(edited.json()["topic"], "Space")
        self.assertEqual(edited.json()["details"], "New focus")
        del payload["details"]
        edited = await self.client.put(f"/scheduled-topics/{job['id']}", json=payload)
        self.assertEqual(edited.json()["details"], "New focus")
        edited = await self.client.put(f"/scheduled-topics/{job['id']}", json={**payload, "details": ""})
        self.assertEqual(edited.json()["details"], "")
        for field, value in (("topic", "  "), ("interval_days", 0), ("schedule_time", "12:30:01")):
            invalid = dict(payload, **{field: value})
            self.assertEqual((await self.client.post("/scheduled-topics", json=invalid)).status_code, 422)

        self.assertEqual((await self.client.delete(f"/scheduled-topics/{job['id']}")).status_code, 200)
        self.assertEqual((await self.client.get("/scheduled-topics")).json(), [])
        self.assertEqual((await self.client.delete(f"/scheduled-topics/{job['id']}")).status_code, 404)
        self.assertEqual((await self.client.put(f"/scheduled-topics/{job['id']}", json=payload)).status_code, 404)

    async def test_overdue_schedule_queued_once_and_advanced(self):
        job = await database.save_scheduled_topic(
            "Due topic", date(2026, 1, 1), time(8), 2, details="Focus on evidence"
        )
        async with database.async_session() as session:
            stored = await session.get(database.ScheduledTopicModel, job["id"])
            stored.next_run = datetime(2026, 1, 1, 8)
            await session.commit()

        now = datetime(2026, 1, 8, 9)
        with patch.object(server.datetime, "datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            with patch.object(server.asyncio, "sleep", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    await server.cron_daemon()

        task_id, topic = server.task_queue.get_nowait()
        self.assertEqual(topic, "Due topic")
        task = server.tasks_db.pop(task_id)
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["details"], "Focus on evidence")
        server.task_queue.task_done()
        self.assertTrue(server.task_queue.empty())

        self.assertEqual(await database.claim_due_scheduled_topics(now), [])
        jobs = await database.list_scheduled_topics()
        self.assertEqual(jobs[0]["next_run"], "2026-01-09T08:00")

    async def test_manual_cron_submits_schedule_details(self):
        jobs = [{"id": "job", "topic": "Fusion", "details": "Recent reactors"}]
        with patch.object(cron, "init_db", new_callable=AsyncMock), \
             patch.object(cron, "list_scheduled_topics", new_callable=AsyncMock, return_value=jobs), \
             patch.object(cron, "urlopen", return_value=io.BytesIO(b'{"task_id": "task"}')) as urlopen, \
             patch("sys.argv", ["cron.py"]), \
             patch.dict("os.environ", {"SHIRATSUYU_TOKEN": "test-token"}), \
             patch("builtins.print"):
            await cron.main()
        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data), {"topic": "Fusion", "details": "Recent reactors"})


class ScheduledTopicMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_schedules_are_preserved_and_migration_is_repeatable(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.exec_driver_sql(
                    "CREATE TABLE scheduled_topics (id VARCHAR PRIMARY KEY, topic VARCHAR NOT NULL, "
                    "start_date VARCHAR NOT NULL, schedule_time VARCHAR NOT NULL, "
                    "interval_days INTEGER NOT NULL, next_run DATETIME NOT NULL)"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO scheduled_topics VALUES "
                    "('old', 'Existing topic', '2099-01-01', '08:00', 1, '2099-01-01 08:00:00')"
                )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            with patch.object(database, "engine", engine), patch.object(database, "async_session", sessions):
                await database.init_db()
                await database.init_db()
                jobs = await database.list_scheduled_topics()
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["topic"], "Existing topic")
                self.assertEqual(jobs[0]["details"], "")
                updated = await database.save_scheduled_topic(
                    "Existing topic", date(2099, 1, 1), time(8), 1, "old", "New details"
                )
                self.assertEqual(updated["details"], "New details")
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()

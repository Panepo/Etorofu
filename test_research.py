import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

import agent
import server


class ResearchRequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.queue_patch = patch.object(server, "task_queue", asyncio.Queue())
        self.tasks_patch = patch.object(server, "tasks_db", {})
        self.auth_patch = patch.object(server, "verify_shiratsuyu_token", new_callable=AsyncMock)
        self.queue_patch.start()
        self.tasks_patch.start()
        self.auth_patch.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-token"},
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.auth_patch.stop()
        self.tasks_patch.stop()
        self.queue_patch.stop()

    async def test_json_and_form_details_and_optional_default(self):
        for kwargs, expected in (
            ({"json": {"topic": "Fusion", "details": "  Recent reactors  "}}, "Recent reactors"),
            ({"data": {"topic": "Fusion", "details": "Practical uses"}}, "Practical uses"),
            ({"json": {"topic": "Fusion"}}, ""),
        ):
            response = await self.client.post("/research", **kwargs)
            self.assertEqual(response.status_code, 200)
            task_id, topic = server.task_queue.get_nowait()
            self.assertEqual(response.json()["task_id"], task_id)
            self.assertEqual(topic, "Fusion")
            self.assertEqual(server.tasks_db[task_id]["details"], expected)
            server.task_queue.task_done()

    async def test_invalid_details_rejected(self):
        response = await self.client.post("/research", json={"topic": "Fusion", "details": ["not text"]})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(server.task_queue.empty())

    async def test_worker_passes_details_to_agents_and_preserves_topic(self):
        task_id = await server.enqueue_research("Fusion", "Recent reactors")

        def finish(task_id, topic, tasks, details):
            tasks[task_id].update(status="completed", result="Report", tags="tag")

        with patch.object(server, "run_knowledge_extraction", side_effect=finish) as run, \
             patch.object(server, "save_report", new_callable=AsyncMock) as save:
            worker = asyncio.create_task(server.worker())
            try:
                await asyncio.wait_for(server.task_queue.join(), timeout=5)
            finally:
                worker.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker
            run.assert_called_once_with(task_id, "Fusion", server.tasks_db, "Recent reactors")
            save.assert_awaited_once_with(task_id=task_id, topic="Fusion", content="Report", tags="tag")


class ResearchAgentTests(unittest.TestCase):
    def test_details_reach_every_stage_and_are_optional(self):
        for details in ("Recent reactors", ""):
            tasks = {"task": {}}
            with patch.object(agent, "_validate_chat_config"), \
                 patch.object(agent, "ChatOpenAI"), \
                 patch.object(agent, "LLM"), \
                 patch.object(agent, "Agent"), \
                 patch.object(agent, "Task") as task, \
                 patch.object(agent, "Crew") as crew, \
                 patch.object(agent, "generate_tags", return_value="tag"):
                crew.return_value.kickoff.return_value = "Report"
                agent.run_knowledge_extraction("task", "Fusion", tasks, details)

            descriptions = [call.kwargs["description"] for call in task.call_args_list]
            self.assertEqual(len(descriptions), 3)
            self.assertIn("Fusion", descriptions[0])
            if details:
                self.assertTrue(all(details in description for description in descriptions))
            else:
                self.assertEqual(descriptions, [
                    "深度搜尋 Fusion 並整理成事實清單。",
                    "根據筆記撰寫初稿。",
                    "進行最終審核與語法修飾。",
                ])
            self.assertEqual(tasks["task"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()

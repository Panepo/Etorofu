import asyncio
import datetime
import os
import uuid
import time
from contextlib import asynccontextmanager
from typing import Dict
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from agent import run_knowledge_extraction
from database import init_db, save_report, load_report, load_all_reports, update_report, update_tags

load_dotenv()

# --- 資料模型與全域狀態 ---
class ResearchRequest(BaseModel):
    topic: str

# 模擬資料庫，儲存任務進度
# status: 'queued', 'searching', 'writing', 'tagging', 'completed', 'failed'
tasks_db: Dict[str, dict] = {}
task_queue = asyncio.Queue()

# --- 背景 Worker ---
async def worker():
    while True:
        task_id, topic = await task_queue.get()
        # 使用 run_in_executor 避免阻塞 FastAPI 的事件循環
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_knowledge_extraction, task_id, topic, tasks_db)
        # Persist completed report and tags to SQLite
        task_data = tasks_db.get(task_id, {})
        if task_data.get("status") == "completed":
            await save_report(
                task_id=task_id,
                topic=topic,
                content=task_data.get("result", ""),
                tags=task_data.get("tags", ""),
            )
        task_queue.task_done()

# --- Cron Worker ---
async def cron_daemon() -> None:
    """Submit a daily report via the shared task queue based on .env settings."""
    topic: str = os.getenv("CRON_TOPIC", "").strip()
    if not topic:
        return

    schedule_time: str = os.getenv("CRON_SCHEDULE", "08:00").strip()
    print(f"[cron] Daemon active — topic={topic!r}  schedule={schedule_time}")

    while True:
        now = datetime.datetime.now()
        target_h, target_m = map(int, schedule_time.split(":"))
        next_run = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
        if next_run <= now:
            next_run += datetime.timedelta(days=1)

        print(f"[cron] Next run at {next_run.strftime('%Y-%m-%d %H:%M')}")
        await asyncio.sleep((next_run - now).total_seconds())

        task_id = str(uuid.uuid4())
        tasks_db[task_id] = {
            "id": task_id,
            "topic": topic,
            "status": "queued",
            "created_at": time.time(),
            "result": None,
        }
        await task_queue.put((task_id, topic))
        print(f"[cron] Queued daily report — task_id={task_id}  topic={topic!r}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(worker())
    asyncio.create_task(cron_daemon())
    yield

app = FastAPI(title="Etorofu Research Hub", lifespan=lifespan)

# --- API 端點 ---

@app.post("/research")
async def start_research(request: Request):
    """提交研究請求，回傳 task_id（支援 JSON 與 form-urlencoded）"""
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        topic = form.get("topic", "")
    else:
        try:
            body = await request.json()
            topic = body.get("topic", "")
        except Exception:
            raise HTTPException(status_code=400, detail="無效的請求格式，請使用 JSON 或 form-urlencoded")

    if not topic:
        raise HTTPException(status_code=400, detail="請提供研究主題")

    task_id = str(uuid.uuid4())
    tasks_db[task_id] = {
        "id": task_id,
        "topic": topic,
        "status": "queued",
        "created_at": time.time(),
        "result": None
    }

    await task_queue.put((task_id, topic))
    return {"task_id": task_id, "message": "任務已加入排隊隊列"}

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    """查詢任務目前的狀態與結果"""
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="找不到該任務")

    # 計算運行時間
    duration = 0
    if task["status"] != "completed" and task["status"] != "failed":
        duration = time.time() - task["created_at"]

    return {
        "task_id": task_id,
        "status": task["status"],
        "topic": task["topic"],
        "elapsed_seconds": round(duration, 1),
        "result": task.get("result"),
        "tags": task.get("tags"),
        "error": task.get("error")
    }

class UpdateReportRequest(BaseModel):
    content: str | None = None
    tags: str | None = None


@app.get("/reports")
async def list_reports():
    """列出所有報告的摘要"""
    return await load_all_reports()


@app.get("/reports/{report_id}")
async def get_report(report_id: str):
    """根據 ID 讀取單一報告"""
    report = await load_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="找不到該報告")
    return {
        "id": report.id,
        "topic": report.topic,
        "content": report.content,
        "tags": report.tags,
        "created_at": report.created_at,
    }


@app.patch("/reports/{report_id}")
async def patch_report(report_id: str, request: UpdateReportRequest):
    """更新報告內文或標籤（至少需提供一個欄位）"""
    if request.content is None and request.tags is None:
        raise HTTPException(status_code=400, detail="請提供 content 或 tags")

    updated = False
    if request.content is not None:
        updated = await update_report(report_id, request.content) or updated
    if request.tags is not None:
        updated = await update_tags(report_id, request.tags) or updated

    if not updated:
        raise HTTPException(status_code=404, detail="找不到該報告")
    return {"message": "報告已更新"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)

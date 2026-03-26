import asyncio
import uuid
import time
from contextlib import asynccontextmanager
from typing import Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from agent import run_knowledge_extraction
from database import init_db, save_report

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(worker())
    yield

app = FastAPI(title="GX10 Qwen3.5 Research Hub", lifespan=lifespan)

# --- API 端點 ---

@app.post("/research")
async def start_research(request: ResearchRequest):
    """提交研究請求，回傳 task_id"""
    if not request.topic:
        raise HTTPException(status_code=400, detail="請提供研究主題")

    task_id = str(uuid.uuid4())
    tasks_db[task_id] = {
        "id": task_id,
        "topic": request.topic,
        "status": "queued",
        "created_at": time.time(),
        "result": None
    }

    await task_queue.put((task_id, request.topic))
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)

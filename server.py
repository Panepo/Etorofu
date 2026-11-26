import asyncio
import datetime
import logging
import os
import uuid
import time
from contextlib import asynccontextmanager
from typing import Dict
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
from agent import run_knowledge_extraction
from database import (
    init_db, save_report, load_report, load_all_reports, update_report, update_tags, delete_report,
    list_scheduled_topics, save_scheduled_topic, delete_scheduled_topic, claim_due_scheduled_topics,
)

load_dotenv()

# --- 資料模型與全域狀態 ---
class ResearchRequest(BaseModel):
    topic: str

# 模擬資料庫，儲存任務進度
# status: 'queued', 'searching', 'writing', 'tagging', 'completed', 'failed'
tasks_db: Dict[str, dict] = {}
task_queue = asyncio.Queue()
logger = logging.getLogger(__name__)


async def enqueue_research(topic: str) -> str:
    task_id = str(uuid.uuid4())
    tasks_db[task_id] = {
        "id": task_id, "topic": topic, "status": "queued",
        "created_at": time.time(), "result": None,
    }
    await task_queue.put((task_id, topic))
    return task_id

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
    """Submit due schedules through the shared task queue."""
    while True:
        try:
            for job in await claim_due_scheduled_topics(datetime.datetime.now()):
                task_id = await enqueue_research(job["topic"])
                logger.info("Queued scheduled report %s for schedule %s", task_id, job["id"])
        except SQLAlchemyError:
            logger.exception("Could not check scheduled topics; retrying")
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(worker())
    asyncio.create_task(cron_daemon())
    yield

app = FastAPI(title="Etorofu Research Hub", lifespan=lifespan)


def shiratsuyu_auth_url() -> str:
    base = os.getenv("SHIRATSUYU_BASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise HTTPException(status_code=503, detail="Shiratsuyu authentication is not configured")
    return f"{base}/auth"


def shiratsuyu_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0, follow_redirects=False)


async def verify_shiratsuyu_token(token: str) -> None:
    try:
        async with shiratsuyu_client() as client:
            response = await client.get(shiratsuyu_auth_url(), headers={"Authorization": f"Bearer {token}"})
    except httpx.RequestError:
        logger.warning("Shiratsuyu token verification failed: service unavailable")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if response.status_code in (401, 403, 404):
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
    if response.status_code != 200:
        logger.warning("Shiratsuyu token verification returned status %s", response.status_code)
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    try:
        user = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid authentication service response")
    if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not user["id"]:
        raise HTTPException(status_code=502, detail="Invalid authentication service response")


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.scope["path"]
    root_path = request.scope.get("root_path", "").rstrip("/")
    if root_path and (path == root_path or path.startswith(root_path + "/")):
        path = path[len(root_path):] or "/"
    if (request.method, path) in {
        ("GET", "/login"), ("POST", "/auth/login"), ("POST", "/auth/logout")
    }:
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not authorization:
        token = request.cookies.get("etorofu_session", "")
    try:
        if not token or not token.isascii() or any(char.isspace() for char in token):
            raise HTTPException(status_code=401, detail="Login required")
        origin = request.headers.get("origin")
        if not authorization and origin and request.method not in ("GET", "HEAD", "OPTIONS"):
            parsed_origin = urlsplit(origin)
            if (parsed_origin.scheme, parsed_origin.netloc) != (request.url.scheme, request.url.netloc):
                raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        await verify_shiratsuyu_token(token)
    except HTTPException as exc:
        if exc.status_code == 401 and request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            response = RedirectResponse(url=f"{request.scope.get('root_path', '')}/login", status_code=303)
        else:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if exc.status_code == 401:
            response.delete_cookie("etorofu_session", path="/")
        return response
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    if request.scope.get("endpoint") is login:
        return JSONResponse({"detail": "Invalid email or password format"}, status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse("static/login.html", headers={"Cache-Control": "no-store"})


@app.post("/auth/login")
async def login(credentials: LoginRequest, request: Request):
    if not credentials.email.strip() or not credentials.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    try:
        async with shiratsuyu_client() as client:
            result = await client.post(
                shiratsuyu_auth_url(),
                json={"email": credentials.email.strip(), "password": credentials.password, "server": "shiratsuyu"},
            )
    except httpx.RequestError:
        logger.warning("Shiratsuyu login failed: service unavailable")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if result.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if result.status_code == 404:
        raise HTTPException(status_code=403, detail="Account is not authorized for Shiratsuyu")
    if not result.is_success:
        logger.warning("Shiratsuyu login returned status %s", result.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"Authentication service rejected the request (HTTP {result.status_code})",
        )
    try:
        user = result.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid authentication service response")
    if (not isinstance(user, dict) or not isinstance(user.get("token"), str) or not user["token"]
            or not user["token"].isascii() or any(char.isspace() for char in user["token"])):
        raise HTTPException(status_code=502, detail="Invalid authentication service response")
    await verify_shiratsuyu_token(user["token"])
    response = JSONResponse({"message": "Login successful"}, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        "etorofu_session", user["token"], httponly=True, secure=request.url.scheme == "https",
        samesite="strict", path="/",
    )
    return response


@app.post("/auth/logout")
async def logout():
    response = JSONResponse({"message": "Logged out"}, headers={"Cache-Control": "no-store"})
    response.delete_cookie("etorofu_session", path="/")
    return response


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

    task_id = await enqueue_research(topic)
    return {"task_id": task_id, "message": "任務已加入排隊隊列"}


class ScheduledTopicRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    start_date: datetime.date
    schedule_time: datetime.time
    interval_days: int = Field(ge=1, le=365)

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Topic must not be blank")
        return value

    @field_validator("schedule_time")
    @classmethod
    def validate_time(cls, value: datetime.time) -> datetime.time:
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("Time must be a local time in HH:MM format")
        return value


@app.get("/scheduled-topics")
async def get_scheduled_topics():
    return await list_scheduled_topics()


@app.post("/scheduled-topics", status_code=201)
async def create_scheduled_topic(request: ScheduledTopicRequest):
    return await save_scheduled_topic(request.topic, request.start_date, request.schedule_time, request.interval_days)


@app.put("/scheduled-topics/{job_id}")
async def edit_scheduled_topic(job_id: str, request: ScheduledTopicRequest):
    job = await save_scheduled_topic(
        request.topic, request.start_date, request.schedule_time, request.interval_days, job_id
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled topic not found")
    return job


@app.delete("/scheduled-topics/{job_id}")
async def remove_scheduled_topic(job_id: str):
    if not await delete_scheduled_topic(job_id):
        raise HTTPException(status_code=404, detail="Scheduled topic not found")
    return {"message": "Scheduled topic deleted"}

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


@app.delete("/reports/{report_id}")
async def remove_report(report_id: str):
    """刪除報告"""
    deleted = await delete_report(report_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="找不到該報告")
    return {"message": "報告已刪除"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)

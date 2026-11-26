import os
import time
import uuid
from datetime import date, datetime, time as clock_time, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import select, update, delete, Text, String
from dotenv import load_dotenv

load_dotenv()

# --- 資料庫設定 ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./research_data.db")
engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ReportModel(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    topic: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[float] = mapped_column(default=time.time)


class ScheduledTopicModel(Base):
    __tablename__ = "scheduled_topics"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    topic: Mapped[str] = mapped_column(String)
    details: Mapped[str] = mapped_column(Text, default="", server_default="")
    start_date: Mapped[str] = mapped_column(String)
    schedule_time: Mapped[str] = mapped_column(String)
    interval_days: Mapped[int]
    next_run: Mapped[datetime]


def next_scheduled_run(start: date, schedule: clock_time, interval_days: int, now: datetime) -> datetime:
    first = datetime.combine(start, schedule)
    if first > now:
        return first
    interval = timedelta(days=interval_days)
    return first + interval * ((now - first) // interval + 1)


def scheduled_topic_dict(job: ScheduledTopicModel) -> dict:
    return {
        "id": job.id,
        "topic": job.topic,
        "details": job.details,
        "start_date": job.start_date,
        "schedule_time": job.schedule_time,
        "interval_days": job.interval_days,
        "next_run": job.next_run.isoformat(timespec="minutes"),
    }


async def list_scheduled_topics() -> list[dict]:
    async with async_session() as session:
        result = await session.execute(select(ScheduledTopicModel).order_by(ScheduledTopicModel.next_run))
        return [scheduled_topic_dict(job) for job in result.scalars()]


async def save_scheduled_topic(
    topic: str, start_date: date, schedule_time: clock_time, interval_days: int,
    job_id: str | None = None, details: str | None = None,
) -> dict | None:
    async with async_session() as session:
        if job_id is None:
            job = ScheduledTopicModel(id=str(uuid.uuid4()))
            session.add(job)
        else:
            job = await session.get(ScheduledTopicModel, job_id)
            if job is None:
                return None
        job.topic = topic
        if details is not None:
            job.details = details
        job.start_date = start_date.isoformat()
        job.schedule_time = schedule_time.strftime("%H:%M")
        job.interval_days = interval_days
        job.next_run = next_scheduled_run(start_date, schedule_time, interval_days, datetime.now())
        await session.commit()
        return scheduled_topic_dict(job)


async def delete_scheduled_topic(job_id: str) -> bool:
    async with async_session() as session:
        result = await session.execute(delete(ScheduledTopicModel).where(ScheduledTopicModel.id == job_id))
        await session.commit()
        return result.rowcount > 0


async def claim_due_scheduled_topics(now: datetime) -> list[dict]:
    """Claim each due schedule once and advance to its next future occurrence."""
    async with async_session() as session:
        result = await session.execute(select(ScheduledTopicModel).where(ScheduledTopicModel.next_run <= now))
        claimed = []
        for job in result.scalars():
            old_next_run = job.next_run
            next_run = next_scheduled_run(
                old_next_run.date(), old_next_run.time(), job.interval_days, now
            )
            updated = await session.execute(
                update(ScheduledTopicModel)
                .where(
                    ScheduledTopicModel.id == job.id,
                    ScheduledTopicModel.next_run == old_next_run,
                    ScheduledTopicModel.topic == job.topic,
                    ScheduledTopicModel.details == job.details,
                    ScheduledTopicModel.interval_days == job.interval_days,
                )
                .values(next_run=next_run)
            )
            if updated.rowcount:
                claimed.append({"id": job.id, "topic": job.topic, "details": job.details})
        await session.commit()
        return claimed


async def init_db():
    """建立所有資料表"""
    async with engine.begin() as conn:
        await conn.exec_driver_sql("BEGIN IMMEDIATE")
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.exec_driver_sql("PRAGMA table_info(scheduled_topics)")
        if "details" not in {row[1] for row in columns}:
            await conn.exec_driver_sql("ALTER TABLE scheduled_topics ADD COLUMN details TEXT NOT NULL DEFAULT ''")


async def get_db():
    """FastAPI Dependency: 提供資料庫 Session"""
    async with async_session() as session:
        yield session


# --- CRUD 操作 ---

async def save_report(task_id: str, topic: str, content: str, tags: str = "") -> None:
    """儲存新報告"""
    async with async_session() as session:
        report = ReportModel(id=task_id, topic=topic, content=content, tags=tags or None, created_at=time.time())
        session.add(report)
        await session.commit()


async def load_report(report_id: str) -> Optional[ReportModel]:
    """根據 ID 讀取單一報告，不存在時回傳 None"""
    async with async_session() as session:
        result = await session.execute(select(ReportModel).where(ReportModel.id == report_id))
        return result.scalar_one_or_none()


async def load_all_reports() -> list[dict]:
    """讀取所有報告的摘要（不含完整內文）"""
    async with async_session() as session:
        result = await session.execute(
            select(ReportModel.id, ReportModel.topic, ReportModel.tags, ReportModel.created_at)
        )
        return [{"id": r[0], "topic": r[1], "tags": r[2], "created_at": r[3]} for r in result.all()]


async def update_report(report_id: str, content: str) -> bool:
    """更新報告內文，回傳是否有列被修改"""
    async with async_session() as session:
        result = await session.execute(
            update(ReportModel).where(ReportModel.id == report_id).values(content=content)
        )
        await session.commit()
        return result.rowcount > 0


async def update_tags(report_id: str, tags: str) -> bool:
    """更新報告標籤，回傳是否有列被修改"""
    async with async_session() as session:
        result = await session.execute(
            update(ReportModel).where(ReportModel.id == report_id).values(tags=tags)
        )
        await session.commit()
        return result.rowcount > 0


async def delete_report(report_id: str) -> bool:
    """刪除報告，回傳是否有列被刪除"""
    async with async_session() as session:
        result = await session.execute(
            delete(ReportModel).where(ReportModel.id == report_id)
        )
        await session.commit()
        return result.rowcount > 0

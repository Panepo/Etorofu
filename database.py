import os
import time
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


async def init_db():
    """建立所有資料表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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

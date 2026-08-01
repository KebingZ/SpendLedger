from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from spendledger.config import Settings


class Base(DeclarativeBase):
    pass


SessionFactory = async_sessionmaker[AsyncSession]


def build_engine(settings: Settings) -> AsyncEngine:
    engine_kwargs: dict[str, object] = {
        "pool_pre_ping": True,
    }
    if settings.database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(settings.database_url, **engine_kwargs)


def build_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

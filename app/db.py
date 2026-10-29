"""SQLAlchemy async connection setup for Neon/PostgreSQL."""
from __future__ import annotations

from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings


def make_database_url(raw_url: str) -> tuple[URL, dict[str, str]]:
    if raw_url.startswith("postgres://"):
        raw_url = "postgresql://" + raw_url[len("postgres://"):]
    url = make_url(raw_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    url = url.set(query=query)
    connect_args: dict[str, str] = {}
    hostname = url.host or ""
    if hostname.endswith(".neon.tech") or sslmode in {"require", "verify-ca", "verify-full"}:
        connect_args["ssl"] = "require"
    return url, connect_args


def create_database(settings: Settings):
    url, connect_args = make_database_url(settings.database_url)
    # Small pool is sufficient for one worker. Each cycle disposes it to enable Neon scale-to-zero.
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        # One slot holds the advisory lock; the second is used by pipeline sessions.
        pool_size=2,
        max_overflow=0,
        connect_args=connect_args,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, sessions

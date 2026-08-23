"""
Test fixtures.

Two test databases are used depending on what's being tested:
- SQLite (in-memory, via aiosqlite) for fast unit tests of things that
  don't depend on Postgres-specific behaviour.
- Real Postgres (via DATABASE_URL, e.g. the docker-compose `postgres`
  service, or a local Postgres) for the concurrency tests, because SQLite's
  locking semantics are not representative of `SELECT ... FOR UPDATE`
  under real concurrent connections. These tests are marked
  `@pytest.mark.postgres` and are skipped automatically if no Postgres is
  reachable (see `pg_engine` fixture) - CI runs them against a Postgres
  service container (see .github/workflows/ci.yml).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.database import Base
from app.models.auction import Auction, AuctionStatus
from app.models.user import User, UserRole

SQLITE_URL = "sqlite+aiosqlite:///:memory:"
POSTGRES_TEST_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://auction:auction@localhost:5432/auction_test_db"
)


@pytest_asyncio.fixture
async def sqlite_session() -> AsyncSession:
    engine = create_async_engine(SQLITE_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_engine():
    """Real Postgres engine for concurrency tests. Skips the test if no
    Postgres instance is reachable (e.g. running unit tests locally without
    docker-compose up)."""
    engine = create_async_engine(POSTGRES_TEST_URL, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable for concurrency tests: {exc}")
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def make_user(session: AsyncSession, *, email: str, role: UserRole = UserRole.BOTH) -> User:
    user = User(
        email=email,
        hashed_password=hash_password("password123"),
        full_name=email.split("@")[0],
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def make_active_auction(
    session: AsyncSession,
    *,
    seller: User,
    starting_price: float = 100.0,
    min_increment: float = 5.0,
    duration_seconds: int = 3600,
) -> Auction:
    now = datetime.now(timezone.utc)
    auction = Auction(
        seller_id=seller.id,
        title="Test Item",
        description="A thing being auctioned in a test",
        starting_price=starting_price,
        current_price=starting_price,
        min_increment=min_increment,
        start_time=now - timedelta(seconds=5),
        end_time=now + timedelta(seconds=duration_seconds),
        status=AuctionStatus.ACTIVE,
    )
    session.add(auction)
    await session.commit()
    await session.refresh(auction)
    return auction

"""
Database connection management for ArXiviz.

Uses SQLite with aiosqlite for local development.
Automatically switches to PostgreSQL when DATABASE_URL environment variable is set (Railway/Render).
"""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

# Use DATABASE_URL from environment (Railway/Render) or fallback to SQLite
DATABASE_URL = os.getenv("DATABASE_URL")

# Railway/Render provide postgres:// URLs, but we need postgresql+asyncpg://
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    # Local development fallback
    DATABASE_URL = "sqlite+aiosqlite:///./arxiviz.db"

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("ENVIRONMENT", "development") == "development",  # Log SQL in dev
    # Additional pool settings for PostgreSQL (ignored for SQLite)
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """
    FastAPI dependency that provides a database session.

    Usage in routes:
        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    Initialize database tables.

    Call this on application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

"""
Database connection management for ArXiviz.

Uses SQLite with aiosqlite for local development.
Switches to PostgreSQL (asyncpg) when the DATABASE_URL environment variable is set.
In production (ENVIRONMENT=production) a Postgres DATABASE_URL is REQUIRED — the
module refuses to import rather than serve from an ephemeral SQLite file.
"""

import logging
import os

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

logger = logging.getLogger(__name__)

SQLITE_FALLBACK_URL = "sqlite+aiosqlite:///./arxiviz.db"
_ASYNCPG_PREFIX = "postgresql+asyncpg://"


def resolve_database_url(raw: str | None, environment: str | None) -> str:
    """Turn the DATABASE_URL env value into the URL the async engine uses.

    Hosted Postgres providers hand out ``postgres://`` / ``postgresql://``
    URLs; the async engine needs ``postgresql+asyncpg://``. An already-correct
    asyncpg URL passes through unchanged (it used to match neither rewrite
    branch and silently fall to SQLite).

    Anything else means SQLite for local development. In production that is
    never what anyone wants — the container's filesystem is ephemeral and the
    API and worker would each get their own empty database — so it raises.
    Messages never include the URL itself: it carries the password.
    """
    url = (raw or "").strip()
    if url.startswith(_ASYNCPG_PREFIX):
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", _ASYNCPG_PREFIX, 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", _ASYNCPG_PREFIX, 1)

    production = (environment or "").strip().lower() == "production"
    if not url:
        if production:
            raise RuntimeError(
                "DATABASE_URL is not set but ENVIRONMENT=production. Refusing to start on the "
                "ephemeral SQLite fallback: set DATABASE_URL to the Postgres connection string "
                "(postgres://, postgresql:// or postgresql+asyncpg://)."
            )
        return SQLITE_FALLBACK_URL

    # Set, but not something we can use. Report the scheme only.
    scheme = url.split("://", 1)[0][:30] if "://" in url else "<no scheme>"
    if production:
        raise RuntimeError(
            f"DATABASE_URL is not a Postgres URL (scheme: {scheme}) but ENVIRONMENT=production. "
            "Refusing to start on the ephemeral SQLite fallback: use postgres://, postgresql:// "
            "or postgresql+asyncpg://."
        )
    logger.warning(
        "DATABASE_URL is set but is not a Postgres URL (scheme: %s) — using local SQLite instead",
        scheme,
    )
    return SQLITE_FALLBACK_URL


# Use DATABASE_URL from environment or fall back to SQLite (never in production)
DATABASE_URL = resolve_database_url(os.getenv("DATABASE_URL"), os.getenv("ENVIRONMENT"))

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


def _missing_model_columns(sync_conn) -> list[str]:
    """``table.column`` for every model column the live table lacks.

    Runs under ``run_sync`` (the inspector is sync-only); works on SQLite and
    Postgres. Extra live columns are fine — only what the ORM will SELECT and
    not find is a problem.
    """
    inspector = inspect(sync_conn)
    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name, schema=table.schema):
            continue  # create_all just ran; a missing table is its failure to report
        live = {column["name"] for column in inspector.get_columns(table.name, schema=table.schema)}
        missing.extend(f"{table.name}.{column.name}" for column in table.columns if column.name not in live)
    return missing


async def init_db():
    """
    Initialize database tables.

    Call this on application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all only creates MISSING TABLES; it never adds a column to a
        # table that already exists, and there is no Alembic. A model column
        # without a migration would otherwise surface as UndefinedColumn 500s
        # at query time — fail the startup probe instead, so the previous
        # revision keeps serving.
        missing = await conn.run_sync(_missing_model_columns)
    if missing:
        raise RuntimeError(
            "Database schema is behind the models — missing column(s): "
            + ", ".join(missing)
            + ". Base.metadata.create_all never alters existing tables; apply a migration "
            "(ALTER TABLE ... ADD COLUMN) before deploying this revision."
        )
    # Idempotent data hygiene, run at every API start (one cheap scan of the
    # visualizations table): hide pre-fix truncated-id video rows where a
    # full-id row exists (see queries.supersede_legacy_truncated_rows).
    from db import queries

    async with async_session_maker() as db:
        retired = await queries.supersede_legacy_truncated_rows(db)
        if retired:
            logger.info("Superseded %d legacy truncated-id visualization row(s)", retired)

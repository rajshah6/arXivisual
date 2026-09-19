"""db/connection.py: URL resolution, the production guard and the schema guard.

Three silent failure modes, each now loud:

* an already-correct ``postgresql+asyncpg://`` URL matched neither rewrite
  branch and fell through to SQLite;
* production with DATABASE_URL unset (or not Postgres) came up "healthy" on an
  ephemeral SQLite file inside the container;
* ``Base.metadata.create_all`` never adds columns to an existing table and
  there is no Alembic, so a new model column only surfaced as UndefinedColumn
  500s at query time. ``init_db`` now fails startup instead (the old revision
  keeps serving).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db.connection as connection
from db.connection import SQLITE_FALLBACK_URL, resolve_database_url

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class TestResolveDatabaseUrl:
    @pytest.mark.parametrize("raw, expected", [
        ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgresql://u:p@host/db?ssl=require", "postgresql+asyncpg://u:p@host/db?ssl=require"),
        # Already correct: must pass through unchanged, not fall to SQLite.
        ("postgresql+asyncpg://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("  postgresql+asyncpg://u:p@host/db\n", "postgresql+asyncpg://u:p@host/db"),
    ])
    @pytest.mark.parametrize("environment", ["development", "production"])
    def test_postgres_urls_resolve_to_asyncpg(self, raw, expected, environment):
        assert resolve_database_url(raw, environment) == expected

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_unset_falls_back_to_sqlite_outside_production(self, raw):
        assert resolve_database_url(raw, "development") == SQLITE_FALLBACK_URL
        assert resolve_database_url(raw, "test") == SQLITE_FALLBACK_URL
        assert resolve_database_url(raw, None) == SQLITE_FALLBACK_URL

    @pytest.mark.parametrize("raw", [None, "", "   "])
    @pytest.mark.parametrize("environment", ["production", "Production", " PRODUCTION "])
    def test_unset_in_production_raises(self, raw, environment):
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            resolve_database_url(raw, environment)

    @pytest.mark.parametrize("raw", [
        "sqlite+aiosqlite:///./arxiviz.db",
        "mysql://root:hunter2@host/db",
        "postgresql+psycopg2://u:hunter2@host/db",  # sync driver: the async engine cannot use it
        "hunter2-not-even-a-url",
    ])
    def test_non_postgres_in_production_raises_without_leaking_the_url(self, raw):
        with pytest.raises(RuntimeError) as excinfo:
            resolve_database_url(raw, "production")
        message = str(excinfo.value)
        assert "not a Postgres URL" in message
        assert "hunter2" not in message  # credentials never reach logs

    def test_unrecognised_url_outside_production_keeps_the_sqlite_fallback(self, caplog):
        with caplog.at_level("WARNING"):
            assert resolve_database_url("mysql://root:hunter2@host/db", "development") == SQLITE_FALLBACK_URL
        assert "hunter2" not in caplog.text
        assert "DATABASE_URL" in caplog.text


def _import_connection(env_overrides: dict[str, str | None]) -> subprocess.CompletedProcess:
    """Import db.connection in a fresh interpreter (the module builds its
    engine at import, so reloading it in-process would swap the engine under
    every other test)."""
    env = dict(os.environ)
    for name, value in env_overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return subprocess.run(
        [sys.executable, "-c", "import db.connection as c; print(c.engine.url.drivername)"],
        capture_output=True, text=True, timeout=120, cwd=BACKEND_ROOT, env=env,
    )


class TestImportTimeGuard:
    def test_production_without_database_url_fails_at_import(self):
        result = _import_connection({"ENVIRONMENT": "production", "DATABASE_URL": None})
        assert result.returncode != 0
        assert "DATABASE_URL is not set" in result.stderr

    def test_production_with_asyncpg_url_builds_a_postgres_engine(self):
        result = _import_connection({
            "ENVIRONMENT": "production",
            "DATABASE_URL": "postgresql+asyncpg://u:p@db.invalid:5432/arxiviz",
        })
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "postgresql+asyncpg"

    def test_development_without_database_url_still_uses_sqlite(self):
        result = _import_connection({"ENVIRONMENT": "development", "DATABASE_URL": None})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "sqlite+aiosqlite"


@pytest.fixture()
async def temp_engine(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schema.db'}")
    monkeypatch.setattr(connection, "engine", engine)
    monkeypatch.setattr(
        connection, "async_session_maker", async_sessionmaker(engine, expire_on_commit=False)
    )
    yield engine
    await engine.dispose()


class TestSchemaGuard:
    async def test_fresh_database_passes(self, temp_engine):
        await connection.init_db()  # create_all builds everything: nothing missing

    async def test_second_startup_on_the_same_database_passes(self, temp_engine):
        await connection.init_db()
        await connection.init_db()

    async def test_extra_live_columns_are_fine(self, temp_engine):
        await connection.init_db()
        async with temp_engine.begin() as conn:
            await conn.execute(text("ALTER TABLE papers ADD COLUMN left_over_from_a_revert VARCHAR"))
        await connection.init_db()

    async def test_model_column_missing_from_an_existing_table_fails_startup(self, temp_engine):
        # The table predates two model columns; create_all will not add them.
        async with temp_engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE processing_jobs ("
                "id VARCHAR PRIMARY KEY, paper_id VARCHAR, status VARCHAR, progress FLOAT, "
                "sections_completed INTEGER, sections_total INTEGER, error TEXT, created_at DATETIME)"
            ))

        with pytest.raises(RuntimeError) as excinfo:
            await connection.init_db()

        message = str(excinfo.value)
        assert "processing_jobs.current_step" in message
        assert "processing_jobs.completed_at" in message
        assert "processing_jobs.status" not in message  # only what is actually missing
        assert "migration" in message.lower()  # says what to do about it

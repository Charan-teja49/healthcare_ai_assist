"""SQLAlchemy-backed access to a selected local SQLite database.

These helpers do not create or migrate application tables. Every engine is
keyed by the canonical database filename, so tests can change database paths
without reusing a connection to a different database.
"""

import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from pathlib import Path
from typing import AsyncIterator, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

DatabasePath = str | os.PathLike[str]


def _database_key(database_path: DatabasePath) -> str:
    """Resolve a file path without creating its parent or touching its data."""
    return os.path.normcase(str(Path(database_path).expanduser().resolve()))


def _foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


@lru_cache(maxsize=32)
def _sync_engine(database_key: str) -> Engine:
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=database_key),
        poolclass=NullPool,
        connect_args={"timeout": 15, "check_same_thread": False},
    )
    event.listen(engine, "connect", _foreign_keys)
    return engine


@lru_cache(maxsize=32)
def _async_engine(database_key: str) -> AsyncEngine:
    engine = create_async_engine(
        URL.create("sqlite+aiosqlite", database=database_key),
        poolclass=NullPool,
        connect_args={"timeout": 15, "check_same_thread": False},
    )
    event.listen(engine.sync_engine, "connect", _foreign_keys)
    return engine


def get_sync_engine(database_path: DatabasePath) -> Engine:
    """Return a file-specific synchronous Engine with no connection pooling."""
    return _sync_engine(_database_key(database_path))


def get_async_engine(database_path: DatabasePath) -> AsyncEngine:
    """Return a file-specific asynchronous Engine with no connection pooling."""
    return _async_engine(_database_key(database_path))


@contextmanager
def sync_session(database_path: DatabasePath) -> Iterator[Session]:
    """Commit an ORM unit of work, or roll it back on any exception."""
    with Session(get_sync_engine(database_path), expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


@asynccontextmanager
async def async_session(database_path: DatabasePath) -> AsyncIterator[AsyncSession]:
    """Commit an async ORM unit of work, or roll it back on any exception."""
    async with AsyncSession(
        get_async_engine(database_path), expire_on_commit=False
    ) as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


@contextmanager
def raw_connection(database_path: DatabasePath) -> Iterator[sqlite3.Connection]:
    """Yield a real sqlite3 connection for existing SQL, not a pool proxy.

    The SQLAlchemy Engine owns connection acquisition/cleanup. SQLite's
    transaction behaviour is retained for existing code, including explicit
    BEGIN IMMEDIATE and executescript calls.
    """
    handle = get_sync_engine(database_path).raw_connection()
    connection = handle.driver_connection
    if not isinstance(connection, sqlite3.Connection):
        handle.close()
        raise TypeError("Expected the sqlite3 driver for raw access")
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        handle.close()

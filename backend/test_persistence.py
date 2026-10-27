"""Persistence tests use only fresh temporary databases, never backend.main."""

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from backend.models import (
    Appointment,
    Base,
    Doctor,
    HealthRecord,
    IngestionKey,
    User,
)
from backend.persistence import (
    async_session,
    get_async_engine,
    get_sync_engine,
    raw_connection,
    sync_session,
)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "test.db"
        Base.metadata.create_all(get_sync_engine(self.path))

    def tearDown(self):
        # NullPool leaves no held-open SQLite files to prevent Windows cleanup.
        get_sync_engine(self.path).dispose()
        asyncio.run(get_async_engine(self.path).dispose())
        self.directory.cleanup()

    def add_user(self, email="patient@example.test"):
        with sync_session(self.path) as session:
            user = User(
                email=email,
                name="Test Patient",
                role="patient",
                password="fixture-only-not-a-real-password",
                consent=1,
                session_key="fixture-session-key",
            )
            session.add(user)
            session.flush()
            return user.id

    def test_sync_orm_round_trip(self):
        user_id = self.add_user()
        with sync_session(self.path) as session:
            user = session.scalar(select(User).where(User.id == user_id))
            self.assertEqual(user.email, "patient@example.test")
            self.assertEqual(user.consent, 1)

    def test_async_orm_round_trip(self):
        async def run():
            async with async_session(self.path) as session:
                session.add(
                    User(
                        email="async@example.test",
                        name="Async Patient",
                        role="patient",
                        password="fixture",
                        consent=1,
                    )
                )
            async with async_session(self.path) as session:
                user = await session.scalar(
                    select(User).where(User.email == "async@example.test")
                )
                self.assertEqual(user.name, "Async Patient")

        asyncio.run(run())
        with sync_session(self.path) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 1)

    def test_raw_connection_is_sqlite_and_commits(self):
        with raw_connection(self.path) as connection:
            self.assertIsInstance(connection, sqlite3.Connection)
            self.assertEqual(connection.row_factory, sqlite3.Row)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            connection.execute(
                "INSERT INTO users(email,name) VALUES(?,?)",
                ("raw@example.test", "Raw Patient"),
            )
        with raw_connection(self.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT name FROM users WHERE email=?", ("raw@example.test",)
                ).fetchone()["name"],
                "Raw Patient",
            )

    def test_raw_transaction_rollback(self):
        with self.assertRaisesRegex(RuntimeError, "forced"):
            with raw_connection(self.path) as connection:
                connection.execute(
                    "INSERT INTO users(email) VALUES(?)", ("rolledback@example.test",)
                )
                raise RuntimeError("forced failure")
        with raw_connection(self.path) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0
            )

    def test_sync_session_rollback(self):
        with self.assertRaisesRegex(RuntimeError, "forced"):
            with sync_session(self.path) as session:
                session.add(User(email="rolledback@example.test"))
                session.flush()
                raise RuntimeError("forced failure")
        with sync_session(self.path) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 0)

    def test_async_session_rollback(self):
        async def run():
            with self.assertRaisesRegex(RuntimeError, "forced"):
                async with async_session(self.path) as session:
                    session.add(User(email="rolledback@example.test"))
                    await session.flush()
                    raise RuntimeError("forced failure")
            async with async_session(self.path) as session:
                self.assertEqual(
                    await session.scalar(select(func.count()).select_from(User)), 0
                )

        asyncio.run(run())

    def test_engine_cache_is_keyed_by_actual_path(self):
        equivalent = self.path.parent / "." / self.path.name
        other = self.path.parent / "other.db"
        self.assertIs(get_sync_engine(self.path), get_sync_engine(equivalent))
        self.assertIs(get_async_engine(self.path), get_async_engine(equivalent))
        self.assertIsNot(get_sync_engine(self.path), get_sync_engine(other))
        self.assertIsNot(get_async_engine(self.path), get_async_engine(other))
        self.assertIsInstance(get_sync_engine(self.path).pool, NullPool)
        self.assertIsInstance(get_async_engine(self.path).pool, NullPool)
        Base.metadata.create_all(get_sync_engine(other))
        self.add_user()
        with raw_connection(other) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0
            )

    def test_foreign_keys_enforced_and_cascade(self):
        with self.assertRaises(IntegrityError):
            with sync_session(self.path) as session:
                session.add(HealthRecord(user_id=999, kind="report", payload="{}"))
                session.flush()
        user_id = self.add_user()
        with sync_session(self.path) as session:
            session.add(HealthRecord(user_id=user_id, kind="report", payload="{}"))
            session.add(
                IngestionKey(user_id=user_id, device_id="device", event_id="event")
            )
        with sync_session(self.path) as session:
            session.execute(delete(User).where(User.id == user_id))
        with raw_connection(self.path) as connection:
            for table in ("records", "ingestion_keys"):
                self.assertEqual(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )

    def test_active_slot_uniqueness_keeps_cancelled_history(self):
        user_id = self.add_user()
        with sync_session(self.path) as session:
            doctor = Doctor(name="Fixture Doctor", specialty="General physician")
            session.add(doctor)
            session.flush()
            doctor_id = doctor.id
        with sync_session(self.path) as session:
            session.add(
                Appointment(
                    user_id=user_id,
                    doctor_id=doctor_id,
                    slot="2030-01-01T10:00",
                    share=0,
                    status="cancelled",
                )
            )
            session.add(
                Appointment(
                    user_id=user_id,
                    doctor_id=doctor_id,
                    slot="2030-01-01T10:00",
                    share=0,
                    status="booked",
                )
            )
        with self.assertRaises(IntegrityError):
            with sync_session(self.path) as session:
                session.add(
                    Appointment(
                        user_id=user_id,
                        doctor_id=doctor_id,
                        slot="2030-01-01T10:00",
                        share=0,
                        status="booked",
                    )
                )
                session.flush()
        with sync_session(self.path) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Appointment)), 2
            )


if __name__ == "__main__":
    unittest.main()

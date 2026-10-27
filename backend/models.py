"""SQLAlchemy 2 mappings of the existing MediAssist local schema.

Importing these declarations performs no schema creation or migration.
Application migrations remain responsible for changing existing databases.
"""

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    password: Mapped[str | None] = mapped_column(Text)
    consent: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    session_key: Mapped[str | None] = mapped_column(Text)


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    specialty: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)


class HealthRecord(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[str | None] = mapped_column(Text)
    created: Mapped[float | None] = mapped_column(Float)


class ReviewCase(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    source: Mapped[str | None] = mapped_column(Text)
    urgency: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'pending'"))
    review: Mapped[str | None] = mapped_column(Text, server_default=text("''"))
    reviewer: Mapped[int | None] = mapped_column(Integer)
    created: Mapped[float | None] = mapped_column(Float)
    record_id: Mapped[int | None] = mapped_column(Integer)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index(
            "active_appointment_slot",
            "doctor_id",
            "slot",
            unique=True,
            sqlite_where=text("status='booked'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"))
    slot: Mapped[str | None] = mapped_column(Text)
    share: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'booked'")
    )


class AuditEntry(Base):
    __tablename__ = "audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str | None] = mapped_column(Text)
    created: Mapped[float | None] = mapped_column(Float)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    message: Mapped[str | None] = mapped_column(Text)
    seen: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    created: Mapped[float | None] = mapped_column(Float)


class IntegrationOutbox(Base):
    __tablename__ = "integration_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    channel: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'mock'"))
    created: Mapped[float | None] = mapped_column(Float)


class IngestionKey(Base):
    __tablename__ = "ingestion_keys"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)

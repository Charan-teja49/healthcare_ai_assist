"""Fictional referral coordinates, distance filtering and scoped local scheduling."""

import math
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.clinical_routes import staff

router = APIRouter()
CITY_COORDINATES = {
    "Mumbai": (19.076, 72.8777),
    "Delhi": (28.6139, 77.209),
    "Bengaluru": (12.9716, 77.5946),
    "Chennai": (13.0827, 80.2707),
    "Pune": (18.5204, 73.8567),
    "Hyderabad": (17.385, 78.4867),
}


def setup(c):
    for name, kind in [
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("verified", "INTEGER DEFAULT 0"),
        ("verification_source", "TEXT"),
    ]:
        if name not in {r["name"] for r in c.execute("PRAGMA table_info(doctors)")}:
            c.execute("ALTER TABLE doctors ADD COLUMN " + name + " " + kind)
    for city, (lat, lon) in CITY_COORDINATES.items():
        c.execute(
            "UPDATE doctors SET latitude=?,longitude=? WHERE city=? AND latitude IS NULL",
            (lat, lon, city),
        )
    c.execute(
        "CREATE TABLE IF NOT EXISTS blocked_slots(doctor_id INTEGER REFERENCES doctors(id),slot TEXT,reason TEXT,created REAL,PRIMARY KEY(doctor_id,slot))"
    )


def haversine(lat1, lon1, lat2, lon2):
    a, b, c, d = map(math.radians, [lat1, lon1, lat2, lon2])
    value = (
        math.sin((c - a) / 2) ** 2
        + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    )
    return 6371 * 2 * math.asin(min(1, math.sqrt(max(0, value))))


def validate_location(latitude, longitude, radius):
    if (latitude is None) != (longitude is None):
        raise HTTPException(422, "Provide both latitude and longitude")
    if latitude is not None and (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise HTTPException(422, "Invalid coordinates")
    if radius is not None and (
        not math.isfinite(radius) or not 1 <= radius <= 5000 or latitude is None
    ):
        raise HTTPException(422, "Radius1–5000km needs both coordinates")


class Block(BaseModel):
    model_config = {"str_strip_whitespace": True}
    doctor_id: int = Field(gt=0)
    slot: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    reason: str = Field(min_length=5, max_length=200)


def allowed(c, user, doctor_id):
    if user["role"] == "admin":
        return
    if not c.execute(
        "SELECT 1 FROM clinician_profiles WHERE user_id=? AND doctor_id=?",
        (user["id"], doctor_id),
    ).fetchone():
        raise HTTPException(
            403, "This specialist schedule belongs to another clinician"
        )


@router.get("/api/clinician/profiles")
def profiles(user=Depends(staff)):
    from backend.main import db

    with db() as c:
        clause = (
            ""
            if user["role"] == "admin"
            else "WHERE id IN (SELECT doctor_id FROM clinician_profiles WHERE user_id=?)"
        )
        return [
            dict(r)
            for r in c.execute(
                "SELECT id,name,specialty,city FROM doctors " + clause,
                () if not clause else (user["id"],),
            )
        ]


@router.get("/api/clinician/blocked-slots")
def blocked(user=Depends(staff)):
    from backend.main import db

    with db() as c:
        clause = (
            ""
            if user["role"] == "admin"
            else "WHERE b.doctor_id IN (SELECT doctor_id FROM clinician_profiles WHERE user_id=?)"
        )
        return [
            dict(r)
            for r in c.execute(
                "SELECT b.*,d.name,d.city FROM blocked_slots b JOIN doctors d ON d.id=b.doctor_id "
                + clause
                + " ORDER BY slot",
                () if not clause else (user["id"],),
            )
        ]


@router.post("/api/clinician/blocked-slots")
def block(body: Block, user=Depends(staff)):
    from datetime import datetime

    from backend.main import IST, audit, checked_day, db, india_now

    try:
        stamp = datetime.fromisoformat(body.slot).replace(tzinfo=IST)
        checked_day(stamp.date().isoformat())
        if (
            stamp <= india_now()
            or stamp.hour < 9
            or stamp.hour >= 18
            or stamp.minute not in (0, 30)
        ):
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Choose a future half-hour clinic slot")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        allowed(c, user, body.doctor_id)
        if not c.execute(
            "SELECT id FROM doctors WHERE id=?", (body.doctor_id,)
        ).fetchone():
            raise HTTPException(404, "Specialist not found")
        if c.execute(
            "SELECT id FROM appointments WHERE doctor_id=? AND slot=? AND status='booked'",
            (body.doctor_id, body.slot),
        ).fetchone():
            raise HTTPException(
                409,
                "A patient has already booked this slot. It cannot be silently blocked.",
            )
        c.execute(
            "INSERT OR REPLACE INTO blocked_slots VALUES(?,?,?,?)",
            (body.doctor_id, body.slot, body.reason.strip(), time.time()),
        )
        audit(c, user["id"], "schedule:blocked")
    return {"blocked": True}


@router.post("/api/clinician/reopen-slot")
def reopen(body: Block, user=Depends(staff)):
    from backend.main import audit, db

    with db() as c:
        allowed(c, user, body.doctor_id)
        c.execute(
            "DELETE FROM blocked_slots WHERE doctor_id=? AND slot=?",
            (body.doctor_id, body.slot),
        )
        audit(c, user["id"], "schedule:reopened")
    return {"reopened": True}

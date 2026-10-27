"""Local educational healthcare prototype. No clinical diagnostic model."""

import asyncio
import json
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import jwt
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.detection import baseline, sustained_rules
from backend.persistence import raw_connection
from backend.schema import migrate_foundation, seed_clinicians

DB = os.getenv("MEDIASSIST_DB", str(Path(__file__).with_name("mediassist.db")))


def load_environment():
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if re.fullmatch(r"[A-Z_][A-Z0-9_]*", key.strip()):
                    os.environ.setdefault(
                        key.strip(), value.strip().strip('"').strip("'")
                    )


load_environment()
DB = os.getenv("MEDIASSIST_DB", DB)
secret_file = Path(DB).with_suffix(".jwt-secret")
secret_file.parent.mkdir(parents=True, exist_ok=True)
if os.getenv("JWT_SECRET"):
    SECRET = os.environ["JWT_SECRET"]
else:
    try:
        with secret_file.open("x", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    SECRET = secret_file.read_text(encoding="utf-8")
hasher = PasswordHasher()
bearer = HTTPBearer()
IST = timezone(timedelta(hours=5, minutes=30))


def india_now():
    return datetime.now(IST)


class StrictModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)


@contextmanager
def db():
    with raw_connection(DB) as connection:
        yield connection


def init(database_path=None):
    with raw_connection(database_path or DB) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT, role TEXT, password TEXT, consent INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS doctors(id INTEGER PRIMARY KEY, name TEXT, specialty TEXT, city TEXT, language TEXT);
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, kind TEXT, payload TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, source TEXT, urgency TEXT, summary TEXT, status TEXT DEFAULT 'pending', review TEXT DEFAULT '', reviewer INTEGER, created REAL);
        CREATE TABLE IF NOT EXISTS appointments(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, doctor_id INTEGER REFERENCES doctors(id), slot TEXT, share INTEGER, UNIQUE(doctor_id,slot));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor INTEGER, action TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, message TEXT, seen INTEGER DEFAULT 0, created REAL);
        CREATE TABLE IF NOT EXISTS integration_outbox(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, channel TEXT, payload TEXT, status TEXT DEFAULT 'mock', created REAL);
        CREATE TABLE IF NOT EXISTS ingestion_keys(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, device_id TEXT, event_id TEXT, PRIMARY KEY(user_id,device_id,event_id));
        """)
        # Bounded, additive migration for existing local databases.
        if "status" not in {
            r["name"] for r in c.execute("PRAGMA table_info(appointments)")
        }:
            c.execute(
                "ALTER TABLE appointments ADD COLUMN status TEXT NOT NULL DEFAULT 'booked'"
            )
        schema = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='appointments'"
        ).fetchone()["sql"]
        if re.search(r"UNIQUE\s*\(\s*doctor_id\s*,\s*slot\s*\)", schema, re.I):
            # Preserve cancelled booking history while allowing that slot to be booked again.
            c.execute(
                "CREATE TABLE appointments_v2(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, doctor_id INTEGER REFERENCES doctors(id), slot TEXT, share INTEGER, status TEXT NOT NULL DEFAULT 'booked')"
            )
            c.execute(
                "INSERT INTO appointments_v2 SELECT id,user_id,doctor_id,slot,share,status FROM appointments"
            )
            c.execute("DROP TABLE appointments")
            c.execute("ALTER TABLE appointments_v2 RENAME TO appointments")
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS active_appointment_slot ON appointments(doctor_id,slot) WHERE status='booked'"
        )
        if "session_key" not in {
            r["name"] for r in c.execute("PRAGMA table_info(users)")
        }:
            c.execute("ALTER TABLE users ADD COLUMN session_key TEXT")
        if "record_id" not in {
            r["name"] for r in c.execute("PRAGMA table_info(cases)")
        }:
            c.execute("ALTER TABLE cases ADD COLUMN record_id INTEGER")
        for email, name, role in [
            ("patient@demo.local", "Aarav Sharma", "patient"),
            ("doctor@demo.local", "Dr. Meera Kapoor", "doctor"),
            ("admin@demo.local", "Demo Administrator", "admin"),
        ]:
            if not c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                c.execute(
                    "INSERT INTO users(email,name,role,password,consent) VALUES(?,?,?,?,1)",
                    (email, name, role, hasher.hash("Demo@12345")),
                )
        for row in c.execute(
            "SELECT id FROM users WHERE session_key IS NULL"
        ).fetchall():
            c.execute(
                "UPDATE users SET session_key=? WHERE id=?",
                (secrets.token_hex(16), row["id"]),
            )
        if not c.execute("SELECT id FROM doctors LIMIT 1").fetchone():
            for i in range(30):
                c.execute(
                    "INSERT INTO doctors(name,specialty,city,language) VALUES(?,?,?,?)",
                    (
                        [
                            "Dr. Meera Kapoor",
                            "Dr. Arjun Rao",
                            "Dr. Ananya Shah",
                            "Dr. Kabir Menon",
                            "Dr. Nisha Iyer",
                        ][i % 5],
                        [
                            "General physician",
                            "Cardiology",
                            "Dermatology",
                            "Pulmonology",
                            "Endocrinology",
                        ][i % 5],
                        [
                            "Mumbai",
                            "Delhi",
                            "Bengaluru",
                            "Chennai",
                            "Pune",
                            "Hyderabad",
                        ][i % 6],
                        ["English, Hindi", "English, Tamil", "English, Marathi"][i % 3],
                    ),
                )

        migrate_foundation(c)
        seed_clinicians(c, hasher)
        from backend.devices import init_device_schema

        init_device_schema(c)
        from backend.audit_chain import setup

        setup(c)
        from backend.conversation import setup as setup_conversations

        setup_conversations(c)
        from backend.documents import setup as setup_documents

        setup_documents(c)
        from backend.referrals import setup as setup_referrals

        setup_referrals(c)
        from backend.notification_dispatch import setup as setup_notifications

        setup_notifications(c)
        from backend.followups import setup as setup_followups

        setup_followups(c)
        if "event_key" not in {
            r["name"] for r in c.execute("PRAGMA table_info(cases)")
        }:
            c.execute("ALTER TABLE cases ADD COLUMN event_key TEXT")
        if "final_guidance" not in {
            r["name"] for r in c.execute("PRAGMA table_info(cases)")
        }:
            c.execute("ALTER TABLE cases ADD COLUMN final_guidance TEXT")
        c.execute(
            "CREATE TABLE IF NOT EXISTS case_actions(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,doctor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,action TEXT,note TEXT,edited_guidance TEXT,created REAL)"
        )
        c.execute(
            "INSERT OR IGNORE INTO schema_versions VALUES(2,?,?)",
            ("Shared device packets and authenticated live fan-out", time.time()),
        )

        for version, description in [
            (3, "Detection models and metadata"),
            (4, "Doctor review actions and integrity chain"),
            (5, "Persistent conversations"),
            (6, "Protected original report documents"),
            (7, "Geospatial directory and blocked slots"),
            (8, "Consented contact and notification outbox"),
            (9, "Patient follow-up history and review requeue clock"),
        ]:
            c.execute(
                "INSERT OR IGNORE INTO schema_versions VALUES(?,?,?)",
                (version, description, time.time()),
            )


@asynccontextmanager
async def lifespan(app):
    init()
    from backend.review_workflow import timeout_worker

    stop = asyncio.Event()
    task = asyncio.create_task(timeout_worker(stop))
    from backend.notification_dispatch import notification_worker

    notification_task = asyncio.create_task(notification_worker(stop))
    app.state.review_worker = task
    try:
        yield
    finally:
        stop.set()
        await task
        await notification_task


app = FastAPI(title="MediAssist AI local prototype", version="0.4.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Avoid reflecting passwords/health text and ensure NaN input cannot break JSON errors.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ]
        },
    )


def current(auth: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        data = jwt.decode(auth.credentials, SECRET, algorithms=["HS256"])
        with db() as c:
            user = c.execute(
                "SELECT id,email,name,role,consent,session_key FROM users WHERE id=?",
                (int(data["sub"]),),
            ).fetchone()
            revoked = (
                data.get("jti")
                and c.execute(
                    "SELECT 1 FROM revoked_tokens WHERE jti=?", (data["jti"],)
                ).fetchone()
            )
        if not user or revoked or data.get("sid") != user["session_key"]:
            raise ValueError()
        return {k: user[k] for k in ("id", "email", "name", "role", "consent")}
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "Session expired. Please sign in again.")


def patient(user=Depends(current)):
    if user["role"] != "patient":
        raise HTTPException(403, "Patient account required")
    if not user["consent"]:
        raise HTTPException(403, "Consent is required to process health data")
    return user


def clinician(user=Depends(current)):
    if user["role"] not in ("doctor", "admin"):
        raise HTTPException(403, "Clinician access required")
    return user


def audit(c, actor, action):
    c.execute(
        "INSERT INTO audit(actor,action,created) VALUES(?,?,?)",
        (actor, action, time.time()),
    )
    from backend.audit_chain import append

    append(c, actor, action, SECRET)


def record(user, kind, data, urgency=None, summary="", connection=None):
    case_id = None
    assigned_id = None
    with nullcontext(connection) if connection is not None else db() as c:
        saved = c.execute(
            "INSERT INTO records(user_id,kind,payload,created) VALUES(?,?,?,?)",
            (user["id"], kind, json.dumps(data), time.time()),
        )
        if urgency:
            inserted = c.execute(
                "INSERT INTO cases(user_id,source,urgency,summary,created,record_id) VALUES(?,?,?,?,?,?)",
                (user["id"], kind, urgency, summary, time.time(), saved.lastrowid),
            )
            case_id = inserted.lastrowid
            assigned_id = c.execute(
                "SELECT clinician_id FROM cases WHERE id=?", (case_id,)
            ).fetchone()[0]
            notify(c, user["id"], f"{urgency.replace('_', ' ')}: {summary[:180]}")
            if urgency == "EMERGENCY":
                from backend.notification_dispatch import queue_emergency

                queue_emergency(c, user["id"])
        audit(c, user["id"], f"created:{kind}")
    if case_id and assigned_id:
        from backend.devices import publish

        publish(assigned_id, {"type": "case_changed", "case_id": case_id})
    return case_id


def notify(c, user_id, message):
    c.execute(
        "INSERT INTO notifications(user_id,message,created) VALUES(?,?,?)",
        (user_id, message, time.time()),
    )


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class Register(Login):
    name: str = Field(min_length=2, max_length=100)
    consent: bool


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": "mediassist",
        "version": "0.4.0",
        "mode": "educational prototype",
    }


@app.post("/api/auth/register")
def register(body: Register):
    if (
        len(body.password) < 10
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email.strip())
        or not body.consent
        or len(body.name.strip()) < 2
    ):
        raise HTTPException(
            422, "Valid email, 10-character password and consent required"
        )
    try:
        with db() as c:
            c.execute(
                "INSERT INTO users(email,name,role,password,consent,session_key) VALUES(?,?,?,?,1,?)",
                (
                    body.email.lower().strip(),
                    body.name.strip(),
                    "patient",
                    hasher.hash(body.password),
                    secrets.token_hex(16),
                ),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Email already registered")
    return login(body)


@app.post("/api/auth/login")
def login(body: Login, request: Request = None):
    from backend.security import check_attempt, clear_attempts, failed_attempt

    key = (
        request.client.host if request and request.client else "local",
        body.email.lower().strip(),
    )
    check_attempt(key)
    with db() as c:
        row = c.execute(
            "SELECT * FROM users WHERE email=?", (body.email.lower().strip(),)
        ).fetchone()
    try:
        hasher.verify(row["password"] if row else hasher.hash("invalid"), body.password)
        if not row:
            raise ValueError()
    except Exception:
        failed_attempt(key)
        raise HTTPException(401, "Incorrect email or password")
    clear_attempts(key)
    return {
        "token": jwt.encode(
            {
                "sub": str(row["id"]),
                "sid": row["session_key"],
                "jti": secrets.token_hex(16),
                "exp": int(time.time()) + 28800,
            },
            SECRET,
            algorithm="HS256",
        ),
        "user": {k: row[k] for k in ("id", "email", "name", "role", "consent")},
    }


@app.post("/api/auth/logout")
def revoke(auth: HTTPAuthorizationCredentials = Depends(bearer), user=Depends(current)):
    data = jwt.decode(auth.credentials, SECRET, algorithms=["HS256"])
    with db() as c:
        if data.get("jti"):
            c.execute(
                "INSERT OR IGNORE INTO revoked_tokens(jti,user_id,expires) VALUES(?,?,?)",
                (data["jti"], user["id"], data["exp"]),
            )
        else:
            c.execute(
                "UPDATE users SET session_key=? WHERE id=?",
                (secrets.token_hex(16), user["id"]),
            )
        audit(c, user["id"], "auth:logout")
    return {"logged_out": True}


@app.get("/api/me")
def me(user=Depends(current)):
    return user


class Consent(BaseModel):
    consent: bool


@app.put("/api/me/consent")
def consent(body: Consent, user=Depends(current)):
    with db() as c:
        c.execute("UPDATE users SET consent=? WHERE id=?", (body.consent, user["id"]))
        audit(c, user["id"], f"consent:{body.consent}")
    return {"consent": body.consent}


@app.get("/api/me/export")
def export(user=Depends(current)):
    with db() as c:
        return {
            "profile": user,
            "documents": [
                dict(row)
                for row in c.execute(
                    "SELECT id,case_id,filename,mime,created FROM documents WHERE user_id=?",
                    (user["id"],),
                )
            ],
            **{
                table: [
                    private_record_view(c, r) if table == "records" else dict(r)
                    for r in c.execute(
                        f"SELECT * FROM {table} WHERE user_id=?", (user["id"],)
                    )
                ]
                for table in (
                    "records",
                    "cases",
                    "appointments",
                    "notifications",
                    "integration_outbox",
                    "emergency_contacts",
                    "conversations",
                    "case_followups",
                )
            },
        }


@app.delete("/api/me")
def erase(user=Depends(current)):
    with db() as c:
        case_ids = {
            r["id"]
            for r in c.execute("SELECT id FROM cases WHERE user_id=?", (user["id"],))
        }
        appointment_ids = {
            r["id"]
            for r in c.execute(
                "SELECT id FROM appointments WHERE user_id=?", (user["id"],)
            )
        }
        for row in c.execute("SELECT id,action FROM audit").fetchall():
            try:
                related = json.loads(row["action"]).get("case") in case_ids
            except (ValueError, AttributeError):
                related = any(
                    row["action"].startswith(f"case:{i}:") for i in case_ids
                ) or any(
                    row["action"].startswith(f"appointment:{i}:")
                    for i in appointment_ids
                )
            if related:
                c.execute("DELETE FROM audit WHERE id=?", (row["id"],))
        c.execute("DELETE FROM users WHERE id=?", (user["id"],))
        c.execute("DELETE FROM audit WHERE actor=?", (user["id"],))
    return {"deleted": True}


class Symptoms(StrictModel):
    symptoms: str = Field(min_length=3, max_length=3000)
    duration: str = Field(default="Not specified", min_length=1, max_length=100)
    severity: int = Field(default=4, ge=1, le=10)
    age: int = Field(default=30, ge=1, le=120)


def triage(text, severity, age):
    text = text.lower()
    for hindi, english in {
        "सीने में दर्द": "chest pain",
        "छाती में दर्द": "chest pain",
        "सांस नहीं": "cannot breathe",
        "साँस नहीं": "cannot breathe",
        "साँस लेने में दिक्कत": "difficulty breathing",
        "सांस लेने में कठिनाई": "difficulty breathing",
        "बेहोश": "unconscious",
        "बहुत खून": "severe bleeding",
        "नीले होंठ": "blue lips",
        "आत्महत्या": "suicid",
        "खुदकुशी": "suicid",
        "ओवरडोज": "overdose",
        "दौरा": "seizure",
    }.items():
        text = text.replace(hindi, english)
    flags = [
        "chest pain",
        "cannot breathe",
        "difficulty breathing",
        "unconscious",
        "severe bleeding",
        "face droop",
        "blue lips",
        "suicid",
        "overdose",
        "seizure",
    ]
    if any(flag in text for flag in flags):
        return {
            "urgency": "EMERGENCY",
            "guidance": "Seek emergency medical care now. Call your local emergency service. Do not wait for an online review.",
            "possibilities": [],
            "specialist": "Emergency care",
        }
    urgency = "URGENT" if severity >= 8 or age < 5 else "CONSULT_SOON"
    possibilities = [
        "Several conditions can cause these symptoms; an examination is needed."
    ]
    specialty = "General physician"
    if any(w in text for w in ["cough", "fever", "sore throat"]):
        possibilities = [
            "A respiratory infection is one possibility, but symptoms alone cannot confirm the cause."
        ]
    if any(w in text for w in ["rash", "itch"]):
        specialty = "Dermatology"
    return {
        "urgency": urgency,
        "guidance": "Arrange an in-person assessment promptly."
        if urgency == "URGENT"
        else "A clinician review has been requested. Seek care sooner if symptoms worsen.",
        "possibilities": possibilities,
        "specialist": specialty,
    }


@app.post("/api/symptoms")
def symptoms(body: Symptoms, user=Depends(patient)):
    result = {
        **triage(body.symptoms, body.severity, body.age),
        "mode": "Rule-based preliminary guidance; not a diagnosis",
        "input": body.model_dump(),
    }
    case_id = record(user, "symptoms", result, result["urgency"], body.symptoms)
    with db() as c:
        case = c.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    from backend.review_workflow import patient_output

    return patient_output(result, case)


class Intake(StrictModel):
    text: str = Field(min_length=3, max_length=3000)


@app.post("/api/integrations/intake")
def intake(body: Intake, user=Depends(patient)):
    immediate = triage(body.text, 4, 30)
    if immediate["urgency"] == "EMERGENCY":
        result = {
            "emergency": immediate,
            "mode": "Emergency rule bypass; no model called",
        }
        record(user, "symptoms", result, "EMERGENCY", body.text)
        return result
    from backend.local_nlp import extract

    return extract(body.text)


class Vitals(StrictModel):
    hr: float = Field(ge=25, le=250)
    spo2: float = Field(ge=50, le=100)
    temperature: float = Field(ge=30, le=45)
    device_id: str = Field(default="simulator", min_length=1, max_length=100)
    event_id: str = Field(min_length=1, max_length=100)
    timestamp: float = Field(default_factory=time.time, gt=0)
    activity: Literal["rest", "walking", "running", "unknown"] = "unknown"
    source: Literal["device", "simulator"] = "device"

    @field_validator("timestamp")
    @classmethod
    def clock_skew(cls, value):
        if value > time.time() + 60:
            raise ValueError("Timestamp must not be more than 60 seconds in the future")
        return value


@app.post("/api/vitals")
def ingest(body: Vitals, user=Depends(patient)):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute(
            "SELECT 1 FROM ingestion_keys WHERE user_id=? AND device_id=? AND event_id=?",
            (user["id"], body.device_id, body.event_id),
        ).fetchone():
            return {"duplicate": True}
        old = [
            json.loads(r["payload"])
            for r in c.execute(
                "SELECT payload FROM records WHERE user_id=? AND kind='vitals' ORDER BY id DESC LIMIT 30",
                (user["id"],),
            )
        ]
        measured = body.model_dump()
        rules = sustained_rules(
            [r for r in old if r.get("device_id") == body.device_id], measured
        )
        personal = baseline(old, measured)
        result = {
            **measured,
            "alert": bool(rules["instant_flags"] or personal["deviation"]),
            "clinical_event_ready": bool(
                rules["sustained_flags"] or personal["deviation"]
            ),
            "rule_flags": rules,
            "baseline_ready": personal["ready"],
            "baseline_samples": personal["sample_count"],
            "baseline_deviation": personal["deviation"],
            "isolation_score": personal["score"],
        }
        try:
            c.execute(
                "INSERT INTO ingestion_keys VALUES(?,?,?)",
                (user["id"], body.device_id, body.event_id),
            )
        except sqlite3.IntegrityError:
            return {"duplicate": True}
        saved = c.execute(
            "INSERT INTO records(user_id,kind,payload,created) VALUES(?,'vitals',?,?)",
            (user["id"], json.dumps(result), time.time()),
        )
        # Coalesce only the same device and same clinical reason.
        event_key = (
            body.device_id
            + ":"
            + ",".join(sorted(rules["sustained_flags"]))
            + (":baseline" if personal["deviation"] else "")
        )
        recent = c.execute(
            "SELECT id FROM cases WHERE user_id=? AND source='vitals' AND event_key=? AND created>?",
            (user["id"], event_key, time.time() - 300),
        ).fetchone()
        if result["clinical_event_ready"] and not recent:
            summary = "Reading outside prototype thresholds or rolling baseline. Verify measurement and seek clinical advice."
            assigned = c.execute(
                "SELECT id FROM users WHERE email='cardio@demo.local'"
            ).fetchone()
            case = c.execute(
                "INSERT INTO cases(user_id,source,urgency,summary,created,record_id,clinician_id,event_key) VALUES(?,'vitals','URGENT',?,?,?,?,?)",
                (
                    user["id"],
                    summary,
                    time.time(),
                    saved.lastrowid,
                    assigned["id"],
                    event_key,
                ),
            )
            from backend.devices import publish

            publish(assigned["id"], {"type": "case_changed", "case_id": case.lastrowid})
            notify(c, user["id"], summary)
        audit(c, user["id"], "created:vitals")
    return result


@app.get("/api/vitals")
def history(user=Depends(patient)):
    with db() as c:
        return [
            json.loads(r["payload"])
            for r in c.execute(
                "SELECT payload FROM records WHERE user_id=? AND kind='vitals' ORDER BY id DESC LIMIT 120",
                (user["id"],),
            )
        ][::-1]


SCENARIOS = {
    "normal_rest": (72, 98, 36.7),
    "arrhythmia_episode": (136, 96, 36.8),
    "low_spo2": (108, 88, 37.1),
    "fever": (102, 96, 39.1),
    "fall": (115, 97, 36.7),
    "leads_off": (72, 98, 36.7),
}


@app.get("/api/simulator/stream")
async def stream(scenario: str = "normal_rest", user=Depends(patient)):
    if scenario not in SCENARIOS:
        raise HTTPException(422, "Unknown scenario")

    async def events():
        for i in range(60):
            with db() as c:
                consent_row = c.execute(
                    "SELECT consent FROM users WHERE id=?", (user["id"],)
                ).fetchone()
            if not consent_row or not consent_row["consent"]:
                yield 'event: consent_required\ndata: {"error":"Consent withdrawn; stream stopped"}\n\n'
                return
            hr, spo2, temp = SCENARIOS[scenario]
            data = {
                "hr": round(hr + math.sin(i) * 2),
                "spo2": spo2,
                "temperature": temp,
                "event_id": secrets.token_hex(8),
                "device_id": "simulator",
                "scenario": scenario,
                "signal": scenario != "leads_off",
                "timestamp": time.time(),
            }
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")


class Scenario(BaseModel):
    scenario: str


@app.post("/api/simulator")
def scenario(body: Scenario, user=Depends(patient)):
    if body.scenario not in SCENARIOS:
        raise HTTPException(422, "Unknown scenario")
    hr, spo2, temp = SCENARIOS[body.scenario]
    if body.scenario in ("fall", "leads_off"):
        record(
            user,
            "device_event",
            {"scenario": body.scenario},
            "URGENT" if body.scenario == "fall" else None,
            "Simulated fall. Check the person and arrange prompt assessment."
            if body.scenario == "fall"
            else "Sensor disconnected. Reconnect before interpreting measurements.",
        )
    if body.scenario == "leads_off":
        return {
            "signal": False,
            "scenario": "leads_off",
            "message": "No valid sensor measurements available",
        }
    return ingest(
        Vitals(hr=hr, spo2=spo2, temperature=temp, event_id=secrets.token_hex(8)), user
    )


LABS = {
    "hemoglobin": (12, 17.5, "g/dL", "Carries oxygen in the blood."),
    "glucose": (70, 99, "mg/dL", "Blood sugar; this demo range assumes fasting."),
    "cholesterol": (0, 200, "mg/dL", "A blood fat measurement."),
    "tsh": (0.4, 4, "mIU/L", "A hormone used to assess thyroid function."),
    "vitamin d": (20, 50, "ng/mL", "Supports bone health."),
}


class Report(StrictModel):
    text: str = Field(min_length=3, max_length=30000)


def parse_report(text):
    from backend.lab_parser import parse

    return parse(text)


def save_report(text, user, document_id=None, document_name=None):
    if len(text.strip()) < 3:
        raise HTTPException(
            422,
            "No readable report text found. Use OCR for an image or paste the report text.",
        )
    rows = parse_report(text)
    result = {
        "values": rows,
        "summary": "Reference intervals vary with laboratory, age, sex, pregnancy, and context. Ask your doctor to interpret these results."
        if rows
        else "No supported values found. Paste labelled results with units, or ask a clinician to review the original report.",
        "questions": [
            "Does the laboratory use a different reference interval?",
            "Do these results need follow-up testing?",
        ],
    }
    result["source_text"] = text
    if document_id is not None:
        result["document_id"] = document_id
        result["document_name"] = document_name
    result["case_id"] = record(
        user,
        "report",
        result,
        "CONSULT_SOON",
        "Medical report requires clinician interpretation",
    )
    return result


@app.post("/api/reports")
def report(body: Report, user=Depends(patient)):
    return save_report(body.text, user)


@app.post("/api/reports/upload")
async def upload(file: UploadFile, user=Depends(patient)):
    content = await file.read(5_000_001)
    if len(content) > 5_000_000:
        raise HTTPException(413, "Maximum file size is 5 MB")
    from backend.documents import extract

    text, mime = await asyncio.to_thread(extract, content, file.filename or "report")
    if len(text.strip()) < 3:
        raise HTTPException(
            422, "No readable report text found. Configure OCR or paste text instead."
        )
    if len(text) > 30000:
        raise HTTPException(
            422,
            "Extracted report exceeds30000 characters. Split it into smaller reports.",
        )
    filename = Path(file.filename or "report").name
    with db() as c:
        saved = c.execute(
            "INSERT INTO documents(user_id,filename,mime,content,created) VALUES(?,?,?,?,?)",
            (user["id"], filename, mime, content, time.time()),
        )
        document_id = saved.lastrowid
    result = save_report(text, user, document_id, filename)
    with db() as c:
        c.execute(
            "UPDATE documents SET case_id=? WHERE id=?",
            (result["case_id"], document_id),
        )
    return result


@app.get("/api/doctors")
def doctors(
    city: str = "",
    specialty: str = "",
    language: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    available_on: str = "",
    user=Depends(current),
):
    from backend.referrals import haversine, validate_location

    validate_location(latitude, longitude, radius_km)
    if available_on:
        checked_day(available_on)
    with db() as c:
        rows = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM doctors WHERE city LIKE ? AND specialty LIKE ? AND language LIKE ?",
                ("%" + city + "%", "%" + specialty + "%", "%" + language + "%"),
            )
        ]
    result = []
    for row in rows:
        row["location_source"] = (
            "Approximate city-centre coordinates for fictional demonstration profiles"
        )
        if latitude is not None:
            row["distance_km"] = (
                round(
                    haversine(latitude, longitude, row["latitude"], row["longitude"]), 2
                )
                if row["latitude"] is not None
                else None
            )
            if radius_km and (
                row["distance_km"] is None or row["distance_km"] > radius_km
            ):
                continue
        if available_on and not available_slots(row["id"], available_on, user)["slots"]:
            continue
        result.append(row)
    if latitude is not None:
        result.sort(
            key=lambda r: (
                r["distance_km"] if r["distance_km"] is not None else float("inf")
            )
        )
    return result


def checked_day(day):
    try:
        selected = date.fromisoformat(day)
        today = india_now().date()
        if selected < today or selected > today + timedelta(days=90):
            raise ValueError()
        return selected
    except ValueError:
        raise HTTPException(
            422, "Choose a date from today through the next 90 days (India time)."
        )


@app.get("/api/doctors/{doctor_id}/slots")
def available_slots(doctor_id: int, day: str, user=Depends(current)):
    selected = checked_day(day)
    with db() as c:
        if not c.execute("SELECT id FROM doctors WHERE id=?", (doctor_id,)).fetchone():
            raise HTTPException(404, "Specialist not found")
        booked = {
            r["slot"]
            for r in c.execute(
                "SELECT slot FROM appointments WHERE doctor_id=? AND status='booked'",
                (doctor_id,),
            )
        }
        booked.update(
            r["slot"]
            for r in c.execute(
                "SELECT slot FROM blocked_slots WHERE doctor_id=?", (doctor_id,)
            )
        )
    slots = []
    for offset in range(18):
        dt = datetime.combine(selected, datetime.min.time(), IST) + timedelta(
            hours=9, minutes=offset * 30
        )
        value = dt.strftime("%Y-%m-%dT%H:%M")
        if dt > india_now() and value not in booked:
            slots.append(value)
    return {"timezone": "Asia/Kolkata", "slots": slots, "day": day}


class Booking(StrictModel):
    doctor_id: int = Field(gt=0)
    slot: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    share: bool = False


@app.post("/api/appointments")
def book(body: Booking, user=Depends(patient)):
    try:
        selected = datetime.fromisoformat(body.slot).replace(tzinfo=IST)
        checked_day(selected.date().isoformat())
        if (
            selected <= india_now()
            or selected.hour < 9
            or selected.hour >= 18
            or selected.minute not in (0, 30)
        ):
            raise ValueError()
    except ValueError:
        raise HTTPException(
            422, "Choose a future half-hour slot between 09:00 and 17:30"
        )
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            if not c.execute(
                "SELECT id FROM doctors WHERE id=?", (body.doctor_id,)
            ).fetchone():
                raise HTTPException(404, "Specialist not found")
            if c.execute(
                "SELECT 1 FROM blocked_slots WHERE doctor_id=? AND slot=?",
                (body.doctor_id, body.slot),
            ).fetchone():
                raise HTTPException(
                    409,
                    "This specialist has blocked the selected slot. Refresh availability.",
                )
            existing = c.execute(
                "SELECT id FROM appointments WHERE doctor_id=? AND slot=? AND status='booked'",
                (body.doctor_id, body.slot),
            ).fetchone()
            if existing:
                raise HTTPException(
                    409,
                    "This slot was just booked. Refresh available times and choose another.",
                )
            c.execute(
                "INSERT INTO appointments(user_id,doctor_id,slot,share) VALUES(?,?,?,?)",
                (user["id"], body.doctor_id, body.slot, body.share),
            )
            audit(c, user["id"], "appointment:created")
            notify(
                c,
                user["id"],
                f"Demo appointment booked for {body.slot.replace('T', ' ')} IST.",
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Doctor unavailable or slot already booked")
    return {"booked": True}


@app.get("/api/appointments")
def appointments(user=Depends(current)):
    with db() as c:
        clause = (
            "WHERE a.user_id=?"
            if user["role"] == "patient"
            else (
                "WHERE a.doctor_id IN (SELECT doctor_id FROM clinician_profiles WHERE user_id=?)"
                if user["role"] == "doctor"
                else ""
            )
        )
        return [
            dict(r)
            for r in c.execute(
                f"SELECT a.*,d.name,d.specialty FROM appointments a JOIN doctors d ON d.id=a.doctor_id {clause} ORDER BY slot",
                (user["id"],) if clause else (),
            )
        ]


@app.post("/api/appointments/{appointment_id}/cancel")
def cancel(appointment_id: int, user=Depends(current)):
    with db() as c:
        row = c.execute(
            "SELECT * FROM appointments WHERE id=? AND user_id=?",
            (appointment_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Appointment not found")
        c.execute(
            "UPDATE appointments SET status='cancelled' WHERE id=?", (appointment_id,)
        )
        audit(c, user["id"], f"appointment:{appointment_id}:cancelled")
    return {"cancelled": True}


@app.get("/api/appointments/{appointment_id}/shared-records")
def shared_records(appointment_id: int, user=Depends(clinician)):
    with db() as c:
        row = c.execute(
            "SELECT a.*,u.consent FROM appointments a JOIN users u ON u.id=a.user_id WHERE a.id=?",
            (appointment_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Appointment not found")
        if (
            user["role"] == "doctor"
            and not c.execute(
                "SELECT 1 FROM clinician_profiles WHERE user_id=? AND doctor_id=?",
                (user["id"], row["doctor_id"]),
            ).fetchone()
        ):
            raise HTTPException(403, "This appointment is assigned to another doctor")
        if not row["share"] or not row["consent"] or row["status"] != "booked":
            raise HTTPException(
                403,
                "Current health consent and appointment sharing consent are both required.",
            )
        audit(c, user["id"], f"appointment:{appointment_id}:shared-records-read")
        return [
            dict(r)
            for r in c.execute(
                "SELECT kind,payload,created FROM records WHERE user_id=? ORDER BY id DESC LIMIT 50",
                (row["user_id"],),
            )
        ]


@app.get("/api/cases")
def cases(user=Depends(current)):
    from backend.review_workflow import expire_pending

    expire_pending()
    with db() as c:
        clause = (
            ""
            if user["role"] == "admin"
            else (
                "WHERE clinician_id=? AND user_id IN (SELECT id FROM users WHERE consent=1)"
                if user["role"] == "doctor"
                else "WHERE user_id=?"
            )
        )
        return [
            dict(r)
            for r in c.execute(
                f"SELECT * FROM cases {clause} ORDER BY CASE urgency WHEN 'EMERGENCY' THEN 0 WHEN 'URGENT' THEN 1 ELSE 2 END,created DESC",
                () if not clause else (user["id"],),
            )
        ]


class Review(StrictModel):
    action: str = Field(
        pattern="^(approved|edited_approved|rejected|needs_info|escalated)$"
    )
    note: str = Field(min_length=5, max_length=2000)
    edited_guidance: str | None = Field(default=None, max_length=3000)


@app.post("/api/cases/{case_id}/review")
def review(case_id: int, body: Review, user=Depends(clinician)):
    if user["role"] != "doctor":
        raise HTTPException(
            403, "Only an assigned doctor can approve clinical guidance"
        )
    with db() as c:
        assigned = c.execute(
            "SELECT clinician_id FROM cases WHERE id=?", (case_id,)
        ).fetchone()
        if assigned and assigned["clinician_id"] != user["id"]:
            raise HTTPException(403, "This case is assigned to another doctor")
        if (
            body.action == "edited_approved"
            and len((body.edited_guidance or "").strip()) < 5
        ):
            raise HTTPException(
                422,
                "Edited approval requires at least five characters of final guidance",
            )
        consent_row = c.execute(
            "SELECT u.consent FROM cases c JOIN users u ON u.id=c.user_id WHERE c.id=?",
            (case_id,),
        ).fetchone()
        if consent_row and not consent_row["consent"]:
            raise HTTPException(403, "Patient health-processing consent is withdrawn")
        row = c.execute(
            "UPDATE cases SET status=?,review=?,reviewer=?,final_guidance=? WHERE id=?",
            (
                body.action,
                body.note,
                user["id"],
                body.edited_guidance if body.action == "edited_approved" else None,
                case_id,
            ),
        )
        if not row.rowcount:
            raise HTTPException(404, "Case not found")
        c.execute(
            "INSERT INTO case_actions(case_id,doctor_id,action,note,edited_guidance,created) VALUES(?,?,?,?,?,?)",
            (
                case_id,
                user["id"],
                body.action,
                body.note,
                body.edited_guidance,
                time.time(),
            ),
        )
        audit(c, user["id"], json.dumps({"case": case_id, **body.model_dump()}))
        owner = c.execute("SELECT user_id FROM cases WHERE id=?", (case_id,)).fetchone()
        notify(
            c,
            owner["user_id"],
            f"Case #{case_id}: {body.action.replace('_', ' ')}. {body.note[:180]}",
        )
    from backend.devices import publish

    publish(user["id"], {"type": "case_changed", "case_id": case_id})
    publish(owner["user_id"], {"type": "case_changed", "case_id": case_id})
    return {"saved": True}


@app.get("/api/audit")
def logs(user=Depends(clinician)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM audit WHERE (?=1 OR actor=?) ORDER BY id DESC LIMIT 100",
                (int(user["role"] == "admin"), user["id"]),
            )
        ]


@app.get("/api/notifications")
def notifications(user=Depends(current)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50",
                (user["id"],),
            )
        ]


@app.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int, user=Depends(current)):
    with db() as c:
        result = c.execute(
            "UPDATE notifications SET seen=1 WHERE id=? AND user_id=?",
            (notification_id, user["id"]),
        )
        if not result.rowcount:
            raise HTTPException(404, "Notification not found")
    return {"seen": True}


@app.get("/api/records")
def records(user=Depends(patient)):
    with db() as c:
        return [
            private_record_view(c, r)
            for r in c.execute(
                "SELECT id,kind,payload,created FROM records WHERE user_id=? ORDER BY id DESC LIMIT 100",
                (user["id"],),
            )
        ]


@app.get("/api/integrations")
def integration_status(user=Depends(current)):
    from backend.integrations import status

    return status()


@app.get("/api/integrations/outbox")
def outbox(user=Depends(current)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM integration_outbox WHERE user_id=? ORDER BY id DESC LIMIT 50",
                (user["id"],),
            )
        ]


@app.get("/api/cases/{case_id}")
def case_detail(case_id: int, user=Depends(current)):
    with db() as c:
        row = c.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if (
            not row
            or (user["role"] == "patient" and row["user_id"] != user["id"])
            or (user["role"] == "doctor" and row["clinician_id"] != user["id"])
        ):
            raise HTTPException(404, "Case not found")
        saved = c.execute(
            "SELECT payload FROM records WHERE id=? AND user_id=?",
            (row["record_id"], row["user_id"]),
        ).fetchone()
        if user["role"] == "doctor":
            consent_row = c.execute(
                "SELECT consent FROM users WHERE id=?", (row["user_id"],)
            ).fetchone()
            if not consent_row or not consent_row["consent"]:
                raise HTTPException(
                    403, "Patient health-processing consent is withdrawn"
                )
        original = json.loads(saved["payload"]) if saved else None
        if user["role"] == "patient" and row["source"] == "symptoms" and original:
            from backend.review_workflow import patient_output

            original = patient_output(original, row)
        actions = [
            dict(a)
            for a in c.execute(
                "SELECT action,note,edited_guidance,created FROM case_actions WHERE case_id=? ORDER BY id",
                (case_id,),
            )
        ]
        followups = [
            dict(f)
            for f in c.execute(
                "SELECT text,created FROM case_followups WHERE case_id=? ORDER BY id",
                (case_id,),
            )
        ]
        return {
            **dict(row),
            "original": original,
            "actions": actions,
            "followups": followups,
        }


from backend.devices import router as device_router

app.include_router(device_router)


@app.get("/api/audit/integrity")
def integrity(user=Depends(current)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access required")
    from backend.audit_chain import verify

    with db() as c:
        return verify(c, SECRET)


def private_record_view(c, row):
    result = dict(row)
    if result.get("kind") == "symptoms":
        from backend.review_workflow import patient_output

        case = c.execute(
            "SELECT * FROM cases WHERE record_id=? ORDER BY id DESC LIMIT 1",
            (result["id"],),
        ).fetchone()
        payload = json.loads(result["payload"])
        if "urgency" in payload:
            result["payload"] = json.dumps(patient_output(payload, case))
    return result


from backend.clinical_routes import router as clinical_router

app.include_router(clinical_router)

from backend.conversation import router as conversation_router

app.include_router(conversation_router)


from backend.documents import router as document_router

app.include_router(document_router)


from backend.referrals import router as referral_router

app.include_router(referral_router)

from backend.notification_dispatch import router as notification_router

app.include_router(notification_router)
from backend.demo import router as demo_router

app.include_router(demo_router)

from backend.language import router as language_router

app.include_router(language_router)

from backend.followups import router as followup_router

app.include_router(followup_router)

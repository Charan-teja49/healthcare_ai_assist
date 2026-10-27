"""Structured conversational symptom intake with emergency-first routing."""

import json
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.devices import require_patient

router = APIRouter()
QUESTIONS = [
    ("symptoms", "Describe the symptoms you are experiencing."),
    ("age", "What is your age in completed years?"),
    ("duration", "How long have you had these symptoms?"),
    ("severity", "How severe are they from1(mild) to10(severe)?"),
    ("associated", "Any other symptoms? Write none if there are no others."),
    (
        "conditions",
        "Any existing medical conditions, pregnancy, regular medicines or allergies? Write none if there are none.",
    ),
]


class Start(BaseModel):
    text: str = Field(default="", max_length=3000)
    language: str = Field(default="en", pattern="^(en|hi|mr|ta)$")


class Answer(BaseModel):
    field: str | None = None
    text: str = Field(min_length=1, max_length=3000)


class Candidate(BaseModel):
    name: str
    rationale: str
    rank: int = Field(ge=1, le=5)


class StructuredAssessment(BaseModel):
    urgency: str = Field(pattern="^(SELF_CARE|CONSULT_SOON|URGENT|EMERGENCY)$")
    possibilities: list[str]
    ranked_conditions: list[Candidate]
    guidance: str
    specialist: str
    mode: str
    input: dict


def setup(c):
    c.execute(
        "CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,fields TEXT,messages TEXT,language TEXT,case_id INTEGER,created REAL,updated REAL)"
    )


def next_question(fields):
    for key, question in QUESTIONS:
        if key not in fields:
            return {"field": key, "text": question}
    return None


def finish(fields, user):
    from backend.main import db, record, triage

    risk = triage(
        fields["symptoms"] + " " + fields.get("associated", ""),
        fields.get("severity", 4),
        fields.get("age", 30),
    )
    candidates = []
    if risk["urgency"] != "EMERGENCY":
        text = (fields["symptoms"] + " " + fields.get("associated", "")).lower()
        if any(k in text for k in ["cough", "fever", "sore throat"]):
            candidates = [
                Candidate(
                    name="Respiratory infection",
                    rationale="Reported respiratory symptoms have several possible causes.",
                    rank=1,
                )
            ]
        elif any(k in text for k in ["rash", "itch"]):
            candidates = [
                Candidate(
                    name="Skin irritation or inflammation",
                    rationale="Reported skin symptoms require context and examination.",
                    rank=1,
                )
            ]
        else:
            candidates = [
                Candidate(
                    name="Cause undetermined",
                    rationale="The available symptoms do not establish a condition.",
                    rank=1,
                )
            ]
    from backend.assessment_model import hypotheses

    model_candidates = hypotheses(fields, risk["urgency"])
    if model_candidates:
        candidates = [Candidate(**item) for item in model_candidates]
    assessment_mode = (
        "Structured local-model hypotheses; assigned doctor approval required"
        if model_candidates
        else "Structured offline preliminary assessment; doctor approval required"
    )
    assessment = StructuredAssessment(
        **risk,
        ranked_conditions=candidates,
        mode=assessment_mode,
        input=fields,
    ).model_dump()
    case_id = record(user, "symptoms", assessment, risk["urgency"], fields["symptoms"])
    with db() as c:
        case = c.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    from backend.review_workflow import patient_output

    return case_id, patient_output(assessment, case)


def view(row, user):
    from backend.main import db

    fields = json.loads(row["fields"])
    question = next_question(fields)
    from backend.language import translate_template

    if question:
        question = {
            **question,
            "text": translate_template(question["text"], row["language"]),
        }
    result = {
        "id": row["id"],
        "messages": json.loads(row["messages"]),
        "fields": fields,
        "question": question,
        "complete": bool(row["case_id"]),
        "assessment": None,
    }
    if row["case_id"]:
        with db() as c:
            case = c.execute(
                "SELECT * FROM cases WHERE id=?", (row["case_id"],)
            ).fetchone()
            saved = (
                c.execute(
                    "SELECT payload FROM records WHERE id=?", (case["record_id"],)
                ).fetchone()
                if case
                else None
            )
        if saved:
            from backend.review_workflow import patient_output

            result["assessment"] = patient_output(json.loads(saved["payload"]), case)
        result["question"] = None
    result["messages"] = [
        {
            **m,
            "text": translate_template(m["text"], row["language"])
            if m["role"] == "assistant"
            else m["text"],
        }
        for m in result["messages"]
    ]
    if result["assessment"] and result["assessment"].get("pending_review"):
        result["assessment"]["guidance"] = translate_template(
            result["assessment"]["guidance"], row["language"]
        )
    if result["assessment"] and result["assessment"].get("urgency") == "EMERGENCY":
        result["assessment"]["guidance"] = translate_template(
            result["assessment"]["guidance"], row["language"]
        )
    return result


@router.post("/api/conversations")
def start(body: Start, user=Depends(require_patient)):
    from backend.main import db, triage

    fields = {}
    messages = []
    case_id = None
    if body.text.strip():
        if len(body.text.strip()) < 3:
            raise HTTPException(422, "Describe symptoms with at least three characters")
        fields["symptoms"] = body.text.strip()
        messages.append({"role": "user", "text": body.text.strip()})
        if triage(body.text, 4, 30)["urgency"] == "EMERGENCY":
            case_id, _ = finish(fields, user)
    question = next_question(fields)
    messages.append(
        {
            "role": "assistant",
            "text": "Emergency guidance applies now; do not wait for review."
            if case_id
            else question["text"],
        }
    )
    identity = secrets.token_hex(16)
    now = time.time()
    with db() as c:
        c.execute(
            "INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?)",
            (
                identity,
                user["id"],
                json.dumps(fields),
                json.dumps(messages),
                body.language,
                case_id,
                now,
                now,
            ),
        )
        row = c.execute(
            "SELECT * FROM conversations WHERE id=?", (identity,)
        ).fetchone()
    return view(row, user)


@router.get("/api/conversations/{identity}")
def get(identity: str, user=Depends(require_patient)):
    from backend.main import db

    with db() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?",
            (identity, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")
    return view(row, user)


@router.post("/api/conversations/{identity}/answer")
def answer(identity: str, body: Answer, user=Depends(require_patient)):
    from backend.main import db, triage

    with db() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?",
            (identity, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")
    if row["case_id"]:
        raise HTTPException(
            409, "This intake is complete. Start a new intake for new symptoms."
        )
    fields = json.loads(row["fields"])
    messages = json.loads(row["messages"])
    question = next_question(fields)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Please answer the current question")
    emergency = triage(text, 4, fields.get("age", 30))["urgency"] == "EMERGENCY"
    if body.field and body.field != question["field"] and not emergency:
        raise HTTPException(
            409,
            "This question has already changed. Reload the intake before answering.",
        )
    if emergency:
        fields["associated"] = (fields.get("associated", "") + " " + text).strip()
        fields.setdefault("symptoms", text)
        case_id, _ = finish(fields, user)
    else:
        key = question["field"]
        if key in ("age", "severity"):
            match = re.fullmatch(
                r"(\d{1,3})(?:\s*(?:years? old|years?|/10))?", text, re.I
            )
            if not match:
                raise HTTPException(422, "Enter a whole number for " + key)
            value = int(match[1])
            if not 1 <= value <= (120 if key == "age" else 10):
                raise HTTPException(422, key + " is outside the allowed range")
        else:
            value = text
            if key == "symptoms" and len(value) < 3:
                raise HTTPException(
                    422, "Describe symptoms with at least three characters"
                )
            if len(value) > (100 if key == "duration" else 3000):
                raise HTTPException(422, "Answer is too long")
        fields[key] = value
        case_id = None
        if next_question(fields) is None:
            case_id, _ = finish(fields, user)
    messages.append({"role": "user", "text": text})
    upcoming = next_question(fields)
    messages.append(
        {
            "role": "assistant",
            "text": "Submitted to your assigned doctor."
            if case_id and not emergency
            else "Emergency guidance applies now; seek immediate care."
            if emergency
            else upcoming["text"],
        }
    )
    with db() as c:
        c.execute(
            "UPDATE conversations SET fields=?,messages=?,case_id=?,updated=? WHERE id=?",
            (json.dumps(fields), json.dumps(messages), case_id, time.time(), identity),
        )
        row = c.execute(
            "SELECT * FROM conversations WHERE id=?", (identity,)
        ).fetchone()
    return view(row, user)


@router.get("/api/conversations")
def list_sessions(user=Depends(require_patient)):
    from backend.main import db

    with db() as c:
        return [
            {"id": r["id"], "complete": bool(r["case_id"]), "updated": r["updated"]}
            for r in c.execute(
                "SELECT id,case_id,updated FROM conversations WHERE user_id=? ORDER BY updated DESC LIMIT 20",
                (user["id"],),
            )
        ]

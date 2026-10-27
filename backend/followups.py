"""Patient answers to an assigned doctor's request, with emergency-first handling."""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.devices import require_patient

router = APIRouter()


def setup(c):
    if "review_due_from" not in {
        r["name"] for r in c.execute("PRAGMA table_info(cases)")
    }:
        c.execute("ALTER TABLE cases ADD COLUMN review_due_from REAL")
    c.execute(
        "CREATE TABLE IF NOT EXISTS case_followups(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,text TEXT NOT NULL,created REAL NOT NULL)"
    )


class Followup(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    text: str = Field(min_length=3, max_length=3000)


@router.post("/api/cases/{case_id}/followup")
def reply(case_id: int, body: Followup, user=Depends(require_patient)):
    from backend.devices import publish
    from backend.main import audit, db, notify, record, triage

    emergency = triage(body.text, 4, 30)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        case = c.execute(
            "SELECT * FROM cases WHERE id=? AND user_id=?", (case_id, user["id"])
        ).fetchone()
        if not case:
            raise HTTPException(404, "Case not found")
        if case["status"] != "needs_info":
            raise HTTPException(409, "This case is not awaiting a patient reply")
        now = time.time()
        c.execute(
            "INSERT INTO case_followups(case_id,user_id,text,created) VALUES(?,?,?,?)",
            (case_id, user["id"], body.text, now),
        )
        c.execute(
            "UPDATE cases SET status='pending',review_due_from=? WHERE id=?",
            (now, case_id),
        )
        record(
            user, "case_followup", {"case_id": case_id, "text": body.text}, connection=c
        )
        urgent = emergency["urgency"] == "EMERGENCY"
        if urgent:
            record(
                user,
                "symptoms",
                {
                    **emergency,
                    "input": {"symptoms": body.text},
                    "mode": "Emergency bypass from a patient follow-up",
                },
                "EMERGENCY",
                body.text,
                connection=c,
            )
        notify(c, user["id"], "Your reply was sent to the assigned doctor.")
        audit(c, user["id"], f"case:{case_id}:patient-followup")
    publish(case["clinician_id"], {"type": "case_changed", "case_id": case_id})
    publish(user["id"], {"type": "case_changed", "case_id": case_id})
    return {
        "saved": True,
        "case_id": case_id,
        "status": "pending",
        "emergency": emergency if urgent else None,
    }

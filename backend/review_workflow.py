"""Clinician release rules and a real background timeout worker."""

import asyncio
import os
import time


def patient_output(payload, case):
    result = dict(payload)
    if result.get("urgency") in ("SELF_CARE", "EMERGENCY"):
        return {**result, "pending_review": False}
    if not case or case["status"] not in ("approved", "edited_approved"):
        result["possibilities"] = []
        if "ranked_conditions" in result:
            result["ranked_conditions"] = []
        result["guidance"] = (
            case["review"]
            if case and case["status"] == "timed_out"
            else "Your preliminary assessment is awaiting the assigned doctor. Seek in-person care promptly if symptoms worsen."
        )
        if case:
            messages = {
                "needs_info": "Your doctor requested more information. Open Doctor review to reply.",
                "rejected": "Your doctor did not approve this assessment. Read their note and seek appropriate in-person advice.",
                "escalated": "Your doctor escalated this case. Seek in-person medical advice promptly.",
            }
            if case["status"] in messages:
                result["guidance"] = messages[case["status"]]
            if case["review"]:
                result["doctor_note"] = case["review"]
        result["pending_review"] = True
    else:
        result["guidance"] = case["final_guidance"] or result.get(
            "guidance", "Arrange clinician follow-up."
        )
        result["doctor_note"] = case["review"]
        result["pending_review"] = False
    if case:
        result["case_id"] = case["id"]
        result["review_status"] = case["status"]
    return result


def expire_pending():
    from backend.main import audit, db, notify

    now = time.time()
    count = 0
    with db() as c:
        rows = c.execute(
            "SELECT id,user_id,urgency FROM cases WHERE status='pending' AND urgency!='EMERGENCY'"
        ).fetchall()
        for case in rows:
            timeout = float(
                os.getenv("URGENT_REVIEW_TIMEOUT_SECONDS", "900")
                if case["urgency"] == "URGENT"
                else os.getenv("REVIEW_TIMEOUT_SECONDS", "86400")
            )
            row = c.execute(
                "SELECT COALESCE(review_due_from,created) AS created FROM cases WHERE id=?",
                (case["id"],),
            ).fetchone()
            if now - row["created"] < timeout:
                continue
            note = "No clinician review within the review window. Arrange in-person assessment; seek urgent care if symptoms worsen."
            changed = c.execute(
                "UPDATE cases SET status='timed_out',review=? WHERE id=? AND status='pending'",
                (note, case["id"]),
            )
            if changed.rowcount:
                notify(c, case["user_id"], note)
                audit(c, None, f"case:{case['id']}:timeout")
                count += 1
    return count


async def timeout_worker(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(expire_pending)
        except Exception:
            # A transient SQLite busy state must not terminate the worker.
            pass
        try:
            await asyncio.wait_for(stop.wait(), 1)
        except asyncio.TimeoutError:
            pass

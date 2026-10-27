"""Explicitly synthetic, time-compressed local scenario replay."""

import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.devices import accept_packet, require_patient
from backend.ingestion import SCENARIOS, SensorPacket, simulate_packet, synthetic_ecg

router = APIRouter()


class DemoRequest(BaseModel):
    scenario: str


@router.post("/api/demo/replay")
def replay(body: DemoRequest, user=Depends(require_patient)):
    if body.scenario not in SCENARIOS:
        raise HTTPException(422, "Unknown demo scenario")
    run = secrets.token_hex(6)
    device = "demo-" + body.scenario
    start = time.time() - 20
    from backend.main import db

    with db() as c:
        last = c.execute(
            "SELECT COALESCE(MAX(id),0) FROM cases WHERE user_id=?", (user["id"],)
        ).fetchone()[0]
    final = None
    fall_detected = False
    # Historical timestamps exercise the duration detector without waiting 20 seconds.
    for index in range(16):
        packet = simulate_packet(
            body.scenario, index, device, start + index
        ).model_copy(update={"event_id": run + "-" + str(index)})
        final = accept_packet(packet, user)
        fall_detected = fall_detected or bool(final.get("fall_detected"))
    if body.scenario not in ("fall", "leads_off"):
        ecg = SensorPacket(
            device_id=device,
            event_id=run + "-ecg",
            timestamp=start + 15,
            source="simulator",
            kind="ecg",
            sample_rate=250,
            samples=synthetic_ecg(
                duration_seconds=6,
                heart_rate=136 if body.scenario == "arrhythmia_episode" else 72,
            ),
        )
        accept_packet(ecg, user)
    with db() as c:
        cases = [
            dict(r)
            for r in c.execute(
                "SELECT id,source,urgency,status FROM cases WHERE user_id=? AND id>?",
                (user["id"], last),
            )
        ]
        related = [
            dict(r)
            for r in c.execute(
                "SELECT c.id,c.source,c.urgency,c.status FROM cases c JOIN records r ON c.record_id=r.id WHERE c.user_id=? AND json_extract(r.payload,'$.device_id')=? AND c.created>? ORDER BY c.id DESC LIMIT 10",
                (user["id"], device, time.time() - 300),
            )
        ]
    return {
        "scenario": body.scenario,
        "synthetic": True,
        "compressed_seconds": 16,
        "packet_count": 16,
        "final": final,
        "fall_detected": fall_detected,
        "new_cases": cases,
        "related_cases": related,
        "note": "Time-compressed synthetic replay; no diagnosis or physical sensor validation.",
    }

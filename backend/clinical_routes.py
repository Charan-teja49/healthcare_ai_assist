import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.devices import _lock, _subscribers

router = APIRouter()


def staff(auth=Depends(HTTPBearer())):
    from backend.main import current

    user = current(auth)
    if user["role"] not in ("doctor", "admin"):
        raise HTTPException(403, "Clinician access required")
    return user


@router.get("/api/cases/{case_id}/ecg-window")
def ecg_window(case_id: int, user=Depends(staff)):
    from backend.main import case_detail, db

    case = case_detail(case_id, user)
    device = (case.get("original") or {}).get("device_id")
    if not device:
        return {
            "samples": [],
            "sample_rate": 250,
            "highlight": None,
            "description": "No ECG device is associated with this submission.",
        }
    with db() as c:
        rows = c.execute(
            "SELECT payload FROM sensor_packets WHERE user_id=? AND device_id=? AND kind='ecg' AND received BETWEEN ? AND ? ORDER BY received LIMIT 20",
            (case["user_id"], device, case["created"] - 10, case["created"] + 10),
        ).fetchall()
    samples = []
    highlights = []
    for row in rows:
        packet = json.loads(row["payload"])
        offset = len(samples)
        samples.extend(packet["samples"])
        packet_start = packet["timestamp"]
        packet_end = packet_start + len(packet["samples"]) / 250
        overlap_start = max(packet_start, case["created"] - 2)
        overlap_end = min(packet_end, case["created"] + 2)
        if overlap_start < overlap_end:
            highlights.append(
                (
                    offset + int((overlap_start - packet_start) * 250),
                    offset + int((overlap_end - packet_start) * 250),
                )
            )
    return {
        "samples": samples,
        "sample_rate": 250,
        "highlight": {
            "start": min(x[0] for x in highlights),
            "end": max(x[1] for x in highlights),
        }
        if highlights
        else None,
        "description": "Signal around the alert time; highlighted timing is not a confirmed ECG abnormality.",
    }


@router.websocket("/ws/cases")
async def case_socket(websocket: WebSocket):
    from backend.main import current

    await websocket.accept()
    registered = None
    try:
        data = await asyncio.wait_for(websocket.receive_json(), 10)
        if not isinstance(data, dict):
            raise ValueError()
        auth = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=data.get("token", "")
        )
        user = current(auth)
        if user["role"] not in ("doctor", "admin"):
            raise HTTPException(403, "Clinician required")
        queue = asyncio.Queue(maxsize=128)
        registered = (asyncio.get_running_loop(), queue)
        with _lock:
            _subscribers[user["id"]].append(registered)
        await websocket.send_json({"type": "ready"})
        while True:
            current(auth)
            try:
                await websocket.send_json(await asyncio.wait_for(queue.get(), 1))
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
    except (
        HTTPException,
        WebSocketDisconnect,
        ValueError,
        RuntimeError,
        asyncio.TimeoutError,
    ):
        try:
            await websocket.close(code=4403)
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        if registered:
            with _lock:
                if registered in _subscribers.get(user["id"], []):
                    _subscribers[user["id"]].remove(registered)

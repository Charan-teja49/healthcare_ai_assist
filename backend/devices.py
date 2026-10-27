"""Shared validated device ingestion, user-scoped live fan-out and trends."""

import asyncio
import json
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.ingestion import SensorPacket, resample_ecg, simulate_packet, synthetic_ecg

router = APIRouter()

_lock = Lock()

_subscribers = defaultdict(list)


def init_device_schema(c):

    c.execute(
        "CREATE TABLE IF NOT EXISTS sensor_packets(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,device_id TEXT,event_id TEXT,kind TEXT,payload TEXT,received REAL,UNIQUE(user_id,device_id,event_id))"
    )


def require_patient(auth=Depends(HTTPBearer())):

    from backend.main import current, patient

    return patient(current(auth))


def publish(user_id, packet):

    with _lock:
        listeners = list(_subscribers.get(user_id, []))

    for loop, queue in listeners:

        def enqueue(q=queue, p=packet):

            if q.full():
                q.get_nowait()

            q.put_nowait(p)

        try:
            loop.call_soon_threadsafe(enqueue)

        except (RuntimeError, WebSocketDisconnect):
            pass


def accept_packet(packet, user):
    from backend.main import Vitals, db, ingest, record

    body = packet.model_dump(exclude_none=True)
    with db() as c:
        if c.execute(
            "SELECT id FROM sensor_packets WHERE user_id=? AND device_id=? AND event_id=?",
            (user["id"], packet.device_id, packet.event_id),
        ).fetchone():
            return {"duplicate": True}
    if packet.kind == "vitals":
        result = ingest(Vitals(**body), user)
        if result.get("duplicate"):
            return result
        body.update(result)
        body["timestamp"] = packet.timestamp
    elif packet.kind == "ecg":
        body["source_sample_rate"] = packet.sample_rate
        try:
            body["samples"] = resample_ecg(packet.samples, packet.sample_rate, 250)
        except ValueError as error:
            raise HTTPException(422, str(error))
        body["sample_rate"] = 250
    else:
        body["signal"] = packet.event != "leads_off"
    if packet.kind == "ecg":
        from backend.ecg_analysis import analyze

        with db() as c:
            previous = c.execute(
                "SELECT payload FROM sensor_packets WHERE user_id=? AND device_id=? AND kind='ecg' ORDER BY id DESC LIMIT 7",
                (user["id"], packet.device_id),
            ).fetchall()
        earlier = [json.loads(r["payload"]) for r in reversed(previous)]
        window = []
        for prior in earlier:
            if packet.timestamp - prior["timestamp"] < 9:
                window.extend(prior["samples"])
        window.extend(body["samples"])
        body["analysis"] = analyze(window[-2500:], 250, body.get("source", "device"))
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute(
            "SELECT id FROM sensor_packets WHERE user_id=? AND device_id=? AND event_id=?",
            (user["id"], packet.device_id, packet.event_id),
        ).fetchone():
            return {"duplicate": True}
        previous = c.execute(
            "SELECT payload FROM sensor_packets WHERE user_id=? AND device_id=? AND kind=? ORDER BY id DESC LIMIT 1",
            (user["id"], packet.device_id, packet.kind),
        ).fetchone()
        if previous and packet.kind == "ecg":
            old = json.loads(previous["payload"])
            gap = (
                packet.timestamp
                - old["timestamp"]
                - len(old["samples"]) / old["sample_rate"]
            )
            if gap > 0.2:
                body["gap_seconds"] = round(gap, 3)
        c.execute(
            "INSERT INTO sensor_packets(user_id,device_id,event_id,kind,payload,received) VALUES(?,?,?,?,?,?)",
            (
                user["id"],
                packet.device_id,
                packet.event_id,
                packet.kind,
                json.dumps(body),
                time.time(),
            ),
        )
        if packet.kind == "ecg":
            record(user, "ecg", body, connection=c)
        elif packet.kind == "event":
            from backend.detection import fall_detect

            previous = c.execute(
                "SELECT payload FROM sensor_packets WHERE user_id=? AND device_id=? ORDER BY id DESC LIMIT 20",
                (user["id"], packet.device_id),
            ).fetchall()
            detected = packet.event == "fall" and fall_detect(
                [json.loads(r["payload"]) for r in previous]
            )
            body["fall_detected"] = bool(detected)
            recent = c.execute(
                "SELECT id FROM cases WHERE user_id=? AND source='device_event' AND created>?",
                (user["id"], time.time() - 300),
            ).fetchone()
            record(
                user,
                "device_event",
                body,
                "URGENT" if detected and not recent else None,
                "Impact followed by stillness detected; check the person promptly."
                if detected
                else "Device signal status: " + packet.event,
                connection=c,
            )
            c.execute(
                "UPDATE sensor_packets SET payload=? WHERE user_id=? AND device_id=? AND event_id=?",
                (json.dumps(body), user["id"], packet.device_id, packet.event_id),
            )
    publish(user["id"], body)
    return body


@router.post("/api/devices/ingest")
def ingest_packet(packet: SensorPacket, user=Depends(require_patient)):

    return accept_packet(packet, user)


@router.get("/api/devices/latest")
def latest(user=Depends(require_patient)):

    from backend.main import db

    with db() as c:
        row = c.execute(
            "SELECT payload FROM sensor_packets WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()

    return json.loads(row["payload"]) if row else {"kind": "empty"}


@router.get("/api/devices/trends")
def trends(hours: int = Query(default=24, ge=1, le=24), user=Depends(require_patient)):

    from backend.main import db

    now = time.time()

    buckets = {}

    start = datetime.fromtimestamp(now, timezone.utc).replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(hours=hours - 1)

    for i in range(hours):
        key = (start + timedelta(hours=i)).isoformat()

        buckets[key] = {
            "hour": key,
            "count": 0,
            "hr": [],
            "spo2": [],
            "temperature": [],
        }

    with db() as c:
        rows = c.execute(
            "SELECT payload,created FROM records WHERE user_id=? AND kind='vitals' AND created>=? ORDER BY created",
            (user["id"], start.timestamp()),
        ).fetchall()

    for row in rows:
        key = (
            datetime.fromtimestamp(row["created"], timezone.utc)
            .replace(minute=0, second=0, microsecond=0)
            .isoformat()
        )

        if key not in buckets:
            continue

        bucket = buckets[key]
        data = json.loads(row["payload"])
        bucket["count"] += 1

        for name in ["hr", "spo2", "temperature"]:
            bucket[name].append(data[name])

    for bucket in buckets.values():
        for name in ["hr", "spo2", "temperature"]:
            values = bucket[name]

            bucket[name] = (
                {
                    "mean": round(sum(values) / len(values), 2),
                    "min": min(values),
                    "max": max(values),
                }
                if values
                else None
            )

    return {
        "hours": hours,
        "buckets": list(buckets.values()),
        "source": "stored readings; empty buckets have no measurements",
    }


@router.websocket("/ws/vitals")
async def socket(websocket: WebSocket):

    from backend.main import current, patient

    await websocket.accept()

    registered = None

    try:
        handshake = await asyncio.wait_for(websocket.receive_json(), 10)

        if not isinstance(handshake, dict):
            raise ValueError("Invalid handshake")
        auth = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=handshake.get("token", "")
        )

        user = patient(current(auth))

        queue = asyncio.Queue(maxsize=128)

        registered = (asyncio.get_running_loop(), queue)

        with _lock:
            _subscribers[user["id"]].append(registered)

        await websocket.send_json({"type": "ready", "transport": "websocket"})

        while True:
            # Revocation and consent apply even when no new packets arrive.

            patient(current(auth))

            try:
                packet = await asyncio.wait_for(queue.get(), 1)

                await websocket.send_json(packet)

            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})

    except HTTPException as error:
        try:
            await websocket.close(code=4401 if error.status_code == 401 else 4403)
        except (RuntimeError, WebSocketDisconnect):
            pass

    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, RuntimeError):
        try:
            await websocket.close(code=4401)

        except (RuntimeError, WebSocketDisconnect):
            pass

    finally:
        if registered:
            with _lock:
                if registered in _subscribers.get(user["id"], []):
                    _subscribers[user["id"]].remove(registered)


@router.post("/api/devices/simulate")
def simulate(body: dict, user=Depends(require_patient)):

    scenario = body.get("scenario", "normal_rest")

    if scenario not in (
        "normal_rest",
        "arrhythmia_episode",
        "low_spo2",
        "fever",
        "fall",
        "leads_off",
    ):
        raise HTTPException(422, "Unknown scenario")

    packet = simulate_packet(scenario, 0).model_copy(
        update={"event_id": secrets.token_hex(12)}
    )

    return accept_packet(packet, user)


@router.get("/api/devices/simulator")
async def simulator(scenario: str = "normal_rest", user=Depends(require_patient)):

    from backend.main import db

    if scenario not in (
        "normal_rest",
        "arrhythmia_episode",
        "low_spo2",
        "fever",
        "fall",
        "leads_off",
    ):
        raise HTTPException(422, "Unknown scenario")

    async def events():

        run = secrets.token_hex(8)

        for index in range(60):
            with db() as c:
                row = c.execute(
                    "SELECT consent FROM users WHERE id=?", (user["id"],)
                ).fetchone()

            if not row or not row["consent"]:
                yield 'event: consent_required\ndata: {"error":"Consent withdrawn"}\n\n'

                return

            packet = simulate_packet(scenario, index).model_copy(
                update={"event_id": run + "-" + str(index), "timestamp": time.time()}
            )

            result = await asyncio.to_thread(accept_packet, packet, user)

            yield "data: " + json.dumps(result) + "\n\n"

            if scenario != "leads_off":
                ecg = SensorPacket(
                    kind="ecg",
                    device_id="simulator",
                    event_id=run + "-ecg-" + str(index),
                    timestamp=time.time(),
                    sample_rate=250,
                    samples=synthetic_ecg(
                        index=index,
                        heart_rate=136 if scenario == "arrhythmia_episode" else 72,
                    ),
                )

                result = await asyncio.to_thread(accept_packet, ecg, user)

                yield "data: " + json.dumps(result) + "\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")

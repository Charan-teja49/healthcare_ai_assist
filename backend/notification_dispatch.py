"""Opt-in notification delivery. No external transport is enabled by default."""

import asyncio
import base64
import json
import os
import re
import time
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field, field_validator

from backend.devices import require_patient


def contact_user(auth=Depends(HTTPBearer())):
    from backend.main import current

    user = current(auth)
    if user["role"] != "patient":
        raise HTTPException(403, "Patient account required")
    return user


router = APIRouter()
GENERIC_MESSAGE = "MediAssist generated urgent guidance. Please check the app and contact the person. This message does not contact emergency services."


def setup(c):
    c.execute(
        "CREATE TABLE IF NOT EXISTS emergency_contacts(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,name TEXT,phone TEXT,consent INTEGER,updated REAL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS push_subscriptions(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,subscription TEXT,created REAL)"
    )
    columns = {r["name"] for r in c.execute("PRAGMA table_info(integration_outbox)")}
    for key, definition in [
        ("attempts", "INTEGER DEFAULT 0"),
        ("next_attempt", "REAL DEFAULT 0"),
        ("provider_id", "TEXT"),
        ("last_error", "TEXT"),
    ]:
        if key not in columns:
            c.execute(f"ALTER TABLE integration_outbox ADD COLUMN {key} {definition}")
    # A crash during transmission is ambiguous: do not automatically send twice.
    c.execute(
        "UPDATE integration_outbox SET status='delivery_unknown',last_error='Service restarted during provider request; inspect provider history before retrying.' WHERE status='sending'"
    )


def sms_ready():
    return (
        os.getenv("SMS_PROVIDER") == "twilio"
        and re.fullmatch(r"AC[0-9a-fA-F]{32}", os.getenv("TWILIO_ACCOUNT_SID", ""))
        is not None
        and bool(os.getenv("TWILIO_AUTH_TOKEN"))
        and re.fullmatch(r"\+[1-9]\d{7,14}", os.getenv("TWILIO_FROM", "")) is not None
    )


def push_ready():
    import importlib.util

    return bool(
        os.getenv("VAPID_PRIVATE_KEY")
        and os.getenv("VAPID_PUBLIC_KEY")
        and os.getenv("VAPID_CONTACT", "").startswith("mailto:")
        and importlib.util.find_spec("pywebpush")
    )


class Contact(BaseModel):
    name: str = Field(default="", max_length=100)
    phone: str = Field(default="", max_length=16)
    consent: bool = False

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value):
        value = value.strip()
        if value and not re.fullmatch(r"\+[1-9]\d{7,14}", value):
            raise ValueError("Use an international phone number, such as +919876543210")
        return value


@router.get("/api/me/emergency-contact")
def contact(user=Depends(contact_user)):
    from backend.main import db

    with db() as c:
        row = c.execute(
            "SELECT name,phone,consent FROM emergency_contacts WHERE user_id=?",
            (user["id"],),
        ).fetchone()
    return {
        **(dict(row) if row else {"name": "", "phone": "", "consent": False}),
        "sms_configured": bool(sms_ready()),
        "push_configured": bool(push_ready()),
    }


@router.put("/api/me/emergency-contact")
def save_contact(body: Contact, user=Depends(contact_user)):
    from backend.main import audit, db

    if body.consent and not user["consent"]:
        raise HTTPException(
            403, "Enable health processing before opting into external alerts"
        )
    if body.consent and (not body.name.strip() or not body.phone):
        raise HTTPException(
            422,
            "A contact name and valid phone number are required for notification consent",
        )
    with db() as c:
        # A changed recipient never receives messages queued for an earlier contact.
        c.execute(
            "UPDATE integration_outbox SET status='cancelled' WHERE user_id=? AND status IN ('queued','retry')",
            (user["id"],),
        )
        c.execute(
            "INSERT INTO emergency_contacts VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,phone=excluded.phone,consent=excluded.consent,updated=excluded.updated",
            (user["id"], body.name.strip(), body.phone, int(body.consent), time.time()),
        )
        audit(c, user["id"], "notification:contact-preference")
    return contact(user)


@router.get("/api/notifications/push/config")
def push_config(user=Depends(require_patient)):
    return {
        "configured": bool(push_ready()),
        "public_key": os.getenv("VAPID_PUBLIC_KEY") if push_ready() else None,
    }


class PushSubscription(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: dict[str, str]

    @field_validator("endpoint")
    @classmethod
    def endpoint_allowed(cls, value):
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname or ""
        allowed = (
            host == "fcm.googleapis.com"
            or host == "updates.push.services.mozilla.com"
            or host.endswith(".notify.windows.com")
            or host == "web.push.apple.com"
        )
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not allowed
        ):
            raise ValueError("A supported browser HTTPS push endpoint is required")
        return value

    @field_validator("keys")
    @classmethod
    def keys_valid(cls, value):
        if set(value) != {"p256dh", "auth"} or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{16,200}=?=?", v) for v in value.values()
        ):
            raise ValueError("Invalid browser push keys")
        return value


@router.post("/api/notifications/push/subscription")
def subscribe(body: PushSubscription, user=Depends(require_patient)):
    from backend.main import db

    if not push_ready():
        raise HTTPException(
            503, "Web Push needs VAPID configuration and the optional pywebpush package"
        )
    with db() as c:
        c.execute(
            "INSERT INTO push_subscriptions VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET subscription=excluded.subscription,created=excluded.created",
            (user["id"], body.model_dump_json(), time.time()),
        )
    return {"saved": True}


@router.delete("/api/notifications/push/subscription")
def unsubscribe(user=Depends(contact_user)):
    from backend.main import db

    with db() as c:
        c.execute("DELETE FROM push_subscriptions WHERE user_id=?", (user["id"],))
        c.execute(
            "UPDATE integration_outbox SET status='cancelled' WHERE user_id=? AND channel='push' AND status IN ('queued','retry')",
            (user["id"],),
        )
    return {"removed": True}


def queue_emergency(c, user_id):
    contact = c.execute(
        "SELECT consent FROM emergency_contacts WHERE user_id=?", (user_id,)
    ).fetchone()
    enabled = bool(contact and contact["consent"] and sms_ready())
    payload = json.dumps(
        {
            "message": GENERIC_MESSAGE,
            "mode": "provider configured"
            if enabled
            else "console mock; no message sent",
        }
    )
    c.execute(
        "INSERT INTO integration_outbox(user_id,channel,payload,status,created) VALUES(?,?,?,?,?)",
        (user_id, "sms", payload, "queued" if enabled else "mock", time.time()),
    )
    if (
        push_ready()
        and c.execute(
            "SELECT 1 FROM push_subscriptions WHERE user_id=?", (user_id,)
        ).fetchone()
    ):
        c.execute(
            "INSERT INTO integration_outbox(user_id,channel,payload,status,created) VALUES(?,?,?,'queued',?)",
            (
                user_id,
                "push",
                json.dumps(
                    {"message": "New urgent guidance is available. Open MediAssist."}
                ),
                time.time(),
            ),
        )


def send_sms(phone, message):
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    data = urllib.parse.urlencode(
        {"To": phone, "From": os.environ["TWILIO_FROM"], "Body": message}
    ).encode()
    request = urllib.request.Request(
        "https://api.twilio.com/2010-04-01/Accounts/" + sid + "/Messages.json",
        data=data,
        method="POST",
    )
    auth = base64.b64encode(
        (sid + ":" + os.environ["TWILIO_AUTH_TOKEN"]).encode()
    ).decode()
    request.add_header("Authorization", "Basic " + auth)
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.load(response)
    if not re.fullmatch(r"(SM|MM)[0-9a-fA-F]{32}", result.get("sid", "")):
        raise ValueError("Invalid provider response")
    return result["sid"]


def dispatch_once(sender=None):
    """Claim a bounded batch. Timeouts are ambiguous and never automatically retried."""
    import urllib.error

    from backend.main import db

    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM integration_outbox WHERE status IN ('queued','retry') AND next_attempt<=? ORDER BY id LIMIT 10",
                (time.time(),),
            )
        ]
        for row in rows:
            c.execute(
                "UPDATE integration_outbox SET status='sending',attempts=attempts+1 WHERE id=?",
                (row["id"],),
            )
    for row in rows:
        with db() as c:
            owner = c.execute(
                "SELECT consent FROM users WHERE id=?", (row["user_id"],)
            ).fetchone()
            contact = c.execute(
                "SELECT * FROM emergency_contacts WHERE user_id=?", (row["user_id"],)
            ).fetchone()
            sub = c.execute(
                "SELECT subscription FROM push_subscriptions WHERE user_id=?",
                (row["user_id"],),
            ).fetchone()
        permitted = bool(
            owner
            and owner["consent"]
            and (
                (
                    row["channel"] == "sms"
                    and contact
                    and contact["consent"]
                    and sms_ready()
                )
                or (row["channel"] == "push" and sub and push_ready())
            )
        )
        status = "cancelled"
        provider_id = None
        error = None
        retry_at = 0
        if permitted:
            try:
                if row["channel"] == "sms":
                    provider_id = (sender or send_sms)(
                        contact["phone"], json.loads(row["payload"])["message"]
                    )
                else:
                    from pywebpush import webpush

                    webpush(
                        subscription_info=json.loads(sub["subscription"]),
                        data=json.dumps(
                            {
                                "title": "MediAssist",
                                "body": "New guidance is available. Open the app.",
                            }
                        ),
                        vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
                        vapid_claims={"sub": os.environ["VAPID_CONTACT"]},
                        timeout=10,
                    )
                status = "accepted"  # Provider acceptance is not proof of recipient delivery.
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                status = "retry" if retryable and row["attempts"] < 2 else "failed"
                retry_at = time.time() + min(300, 30 * 2 ** row["attempts"])
                error = "Provider HTTP " + str(exc.code)
            except Exception:
                # Includes network timeouts: the provider may already have accepted.
                status = "delivery_unknown"
                error = "Delivery could not be confirmed. Inspect provider history before retrying."
        with db() as c:
            c.execute(
                "UPDATE integration_outbox SET status=?,provider_id=?,last_error=?,next_attempt=? WHERE id=?",
                (status, provider_id, error, retry_at, row["id"]),
            )
    return len(rows)


async def notification_worker(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(dispatch_once)
        except Exception:
            # Transient database contention must not terminate delivery processing.
            pass
        try:
            await asyncio.wait_for(stop.wait(), 2)
        except asyncio.TimeoutError:
            pass

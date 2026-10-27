"""Append-only, keyed integrity chain containing no clinical text or raw account IDs."""

import hashlib
import hmac
import json
import secrets
import time


def setup(c):
    if "audit_identity" not in {
        r["name"] for r in c.execute("PRAGMA table_info(users)")
    }:
        c.execute("ALTER TABLE users ADD COLUMN audit_identity TEXT")
    for row in c.execute(
        "SELECT id FROM users WHERE audit_identity IS NULL"
    ).fetchall():
        c.execute(
            "UPDATE users SET audit_identity=? WHERE id=?",
            (secrets.token_hex(24), row["id"]),
        )
    c.execute(
        "CREATE TABLE IF NOT EXISTS audit_chain(id INTEGER PRIMARY KEY,actor_digest TEXT,category TEXT,created REAL,previous TEXT,digest TEXT)"
    )
    c.execute(
        "CREATE TRIGGER IF NOT EXISTS immutable_audit_update BEFORE UPDATE ON audit_chain BEGIN SELECT RAISE(ABORT,'Audit integrity rows are append-only'); END"
    )
    c.execute(
        "CREATE TRIGGER IF NOT EXISTS immutable_audit_delete BEFORE DELETE ON audit_chain BEGIN SELECT RAISE(ABORT,'Audit integrity rows are append-only'); END"
    )


def signature(secret, actor, category, created, previous):
    data = json.dumps([actor, category, created, previous], separators=(",", ":"))
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def append(c, actor, action, secret):
    row = (
        c.execute("SELECT audit_identity FROM users WHERE id=?", (actor,)).fetchone()
        if actor is not None
        else None
    )
    if row and not row["audit_identity"]:
        identity = secrets.token_hex(24)
        c.execute("UPDATE users SET audit_identity=? WHERE id=?", (identity, actor))
    else:
        identity = row["audit_identity"] if row else "system"
    actor_digest = hashlib.sha256(identity.encode()).hexdigest()
    try:
        parsed = json.loads(action)
        category = (
            "clinical_review:" + str(parsed.get("action", "event"))
            if isinstance(parsed, dict)
            else "operation"
        )
    except ValueError:
        category = (
            action.split(":")[0]
            + ":"
            + ("created" if action.startswith("created:") else "event")
        )
    previous = c.execute(
        "SELECT digest FROM audit_chain ORDER BY id DESC LIMIT 1"
    ).fetchone()
    previous = previous["digest"] if previous else "0" * 64
    created = time.time()
    digest = signature(secret, actor_digest, category, created, previous)
    c.execute(
        "INSERT INTO audit_chain(actor_digest,category,created,previous,digest) VALUES(?,?,?,?,?)",
        (actor_digest, category, created, previous, digest),
    )


def verify(c, secret):
    previous = "0" * 64
    count = 0
    for row in c.execute("SELECT * FROM audit_chain ORDER BY id"):
        count += 1
        if row["previous"] != previous or row["digest"] != signature(
            secret, row["actor_digest"], row["category"], row["created"], previous
        ):
            return {"valid": False, "checked": count, "first_bad_row": row["id"]}
        previous = row["digest"]
    return {"valid": True, "checked": count, "first_bad_row": None}

import json
import secrets
import sqlite3
import time
import unittest

from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.main import app, db


class ReviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def login(self, email):
        r = self.client.post(
            "/api/auth/login", json={"email": email, "password": "Demo@12345"}
        )
        return {"Authorization": "Bearer " + r.json()["token"]}

    def patient(self):
        r = self.client.post(
            "/api/auth/register",
            json={
                "email": secrets.token_hex(6) + "@review.test",
                "name": "Review Fixture",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        return {"Authorization": "Bearer " + r.json()["token"]}

    def submit(self, h, text="cough for two days"):
        r = self.client.post("/api/symptoms", headers=h, json={"symptoms": text})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_consultation_held_from_all_patient_views(self):
        h = self.patient()
        result = self.submit(h)
        self.assertTrue(result["pending_review"])
        self.assertEqual(result["possibilities"], [])
        for path in ["/api/records", "/api/me/export"]:
            data = self.client.get(path, headers=h).json()
            self.assertNotIn(
                "A respiratory infection is one possibility", json.dumps(data)
            )
        doctor = self.login("doctor@demo.local")
        original = self.client.get(
            "/api/cases/" + str(result["case_id"]), headers=doctor
        ).json()["original"]
        self.assertTrue(original["possibilities"])

    def test_emergency_not_held(self):
        result = self.submit(self.patient(), "chest pain")
        self.assertFalse(result["pending_review"])
        self.assertIn("now", result["guidance"])

    def test_edited_approval_releases_only_final_guidance(self):
        h = self.patient()
        result = self.submit(h)
        case = result["case_id"]
        doctor = self.login("doctor@demo.local")
        r = self.client.post(
            f"/api/cases/{case}/review",
            headers=doctor,
            json={
                "action": "edited_approved",
                "note": "Reviewed the original symptom narrative.",
                "edited_guidance": "Arrange a visit with your treating clinician today.",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        released = self.client.get(f"/api/cases/{case}", headers=h).json()
        self.assertFalse(released["original"]["pending_review"])
        self.assertEqual(
            released["original"]["guidance"],
            "Arrange a visit with your treating clinician today.",
        )
        self.assertEqual(released["actions"][0]["action"], "edited_approved")

    def test_edit_requires_guidance(self):
        h = self.patient()
        result = self.submit(h)
        r = self.client.post(
            "/api/cases/" + str(result["case_id"]) + "/review",
            headers=self.login("doctor@demo.local"),
            json={
                "action": "edited_approved",
                "note": "Valid reason but no final advice",
            },
        )
        self.assertEqual(r.status_code, 422)

    def test_timeout_happens_without_queue_read(self):
        h = self.patient()
        result = self.submit(h)
        with db() as c:
            c.execute(
                "UPDATE cases SET created=? WHERE id=?",
                (time.time() - 90000, result["case_id"]),
            )
        time.sleep(1.4)
        with db() as c:
            state = c.execute(
                "SELECT status FROM cases WHERE id=?", (result["case_id"],)
            ).fetchone()["status"]
        self.assertEqual(state, "timed_out")

    def test_audit_chain_append_only_and_valid(self):
        h = self.patient()
        self.submit(h)
        with db() as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("DELETE FROM audit_chain")
        admin = self.login("admin@demo.local")
        r = self.client.get("/api/audit/integrity", headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["valid"])
        self.assertEqual(
            self.client.get("/api/audit/integrity", headers=h).status_code, 403
        )

    def test_withdrawn_consent_blocks_doctor_processing(self):
        h = self.patient()
        result = self.submit(h)
        self.client.put("/api/me/consent", headers=h, json={"consent": False})
        doctor = self.login("doctor@demo.local")
        self.assertEqual(
            self.client.get(
                "/api/cases/" + str(result["case_id"]), headers=doctor
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/cases/" + str(result["case_id"]) + "/review",
                headers=doctor,
                json={"action": "approved", "note": "Consent must be active"},
            ).status_code,
            403,
        )

    def test_clinician_queue_gets_live_case_event(self):
        patient = self.patient()
        doctor = self.login("doctor@demo.local")
        with self.client.websocket_connect("/ws/cases") as ws:
            ws.send_json({"token": doctor["Authorization"].split(" ", 1)[1]})
            self.assertEqual(ws.receive_json()["type"], "ready")
            result = self.submit(patient)
            message = ws.receive_json()
            while message.get("type") == "heartbeat":
                message = ws.receive_json()
            self.assertEqual(message["case_id"], result["case_id"])

    def test_integrity_remains_valid_after_private_erasure(self):
        patient = self.patient()
        self.submit(patient)
        self.client.delete("/api/me", headers=patient)
        self.assertTrue(
            self.client.get(
                "/api/audit/integrity", headers=self.login("admin@demo.local")
            ).json()["valid"]
        )

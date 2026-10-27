import json
import secrets
import time
import unittest

from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.detection import sustained_rules
from backend.main import app, current, db, record


class FinalWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def patient(self):
        response = self.client.post(
            "/api/auth/register",
            json={
                "name": "Final Workflow Fixture",
                "email": secrets.token_hex(7) + "@final.test",
                "password": "Demo@12345",
                "consent": True,
            },
        )
        token = response.json()["token"]
        return {"Authorization": "Bearer " + token}, current(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )

    def test_can_withdraw_contact_consent_with_health_processing_paused(self):
        h, _ = self.patient()
        body = {"name": "Fictional Contact", "phone": "+919876543210", "consent": True}
        self.assertEqual(
            self.client.put(
                "/api/me/emergency-contact", headers=h, json=body
            ).status_code,
            200,
        )
        self.client.put("/api/me/consent", headers=h, json={"consent": False})
        body["consent"] = False
        self.assertEqual(
            self.client.put(
                "/api/me/emergency-contact", headers=h, json=body
            ).status_code,
            200,
        )
        body["consent"] = True
        self.assertEqual(
            self.client.put(
                "/api/me/emergency-contact", headers=h, json=body
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                "/api/notifications/push/subscription", headers=h
            ).status_code,
            200,
        )

    def test_ecg_window_uses_associated_device_and_sample_overlap(self):
        _, user = self.patient()
        created = time.time()
        identity = record(
            user,
            "vitals",
            {"device_id": "linked-device"},
            "URGENT",
            "Fictional context test",
        )
        with db() as c:
            c.execute("UPDATE cases SET created=? WHERE id=?", (created, identity))
            for device in ["linked-device", "unrelated-device"]:
                payload = {
                    "device_id": device,
                    "kind": "ecg",
                    "sample_rate": 250,
                    "samples": [0.1] * 1500,
                    "timestamp": created - 5,
                }
                c.execute(
                    "INSERT INTO sensor_packets(user_id,device_id,event_id,kind,payload,received) VALUES(?,?,?,?,?,?)",
                    (
                        user["id"],
                        device,
                        secrets.token_hex(4),
                        "ecg",
                        json.dumps(payload),
                        created,
                    ),
                )
        token = self.client.post(
            "/api/auth/login",
            json={"email": "doctor@demo.local", "password": "Demo@12345"},
        ).json()["token"]
        response = self.client.get(
            "/api/cases/" + str(identity) + "/ecg-window",
            headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(len(result["samples"]), 1500)
        self.assertAlmostEqual(result["highlight"]["start"], 750, delta=1)
        self.assertAlmostEqual(result["highlight"]["end"], 1500, delta=1)

    def test_future_history_does_not_sustain_current_alert(self):
        now = time.time()
        row = {
            "timestamp": now,
            "hr": 130,
            "spo2": 98,
            "temperature": 36.7,
            "activity": "rest",
        }
        history = [{**row, "timestamp": now + 10}, {**row, "timestamp": now - 1}]
        self.assertEqual(sustained_rules(history, row)["sustained_flags"], [])

    def test_export_includes_contacts_and_document_metadata(self):
        h, _ = self.patient()
        upload = self.client.post(
            "/api/reports/upload",
            headers=h,
            files={"file": ("fixture.txt", b"TSH: 2.1 mIU/L")},
        ).json()
        self.client.put(
            "/api/me/emergency-contact",
            headers=h,
            json={"name": "Fictional", "phone": "+919876543210", "consent": False},
        )
        result = self.client.get("/api/me/export", headers=h).json()
        self.assertEqual(result["documents"][0]["id"], upload["document_id"])
        self.assertNotIn("content", result["documents"][0])
        self.assertEqual(result["emergency_contacts"][0]["consent"], 0)

    def test_legacy_vitals_reject_future_clock_skew(self):
        h, _ = self.patient()
        response = self.client.post(
            "/api/vitals",
            headers=h,
            json={
                "hr": 72,
                "spo2": 98,
                "temperature": 36.7,
                "event_id": "future-clock",
                "timestamp": time.time() + 120,
            },
        )
        self.assertEqual(response.status_code, 422)

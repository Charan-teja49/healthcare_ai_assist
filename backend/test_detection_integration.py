import secrets
import time
import unittest

from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.main import app


class DetectionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def patient(self):
        r = self.client.post(
            "/api/auth/register",
            json={
                "email": secrets.token_hex(6) + "@detection.test",
                "name": "Detection Fixture",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_sustained_high_pulse_routes_to_cardiologist(self):
        h = self.patient()
        start = time.time() - 15
        for i in range(11):
            r = self.client.post(
                "/api/devices/ingest",
                headers=h,
                json={
                    "kind": "vitals",
                    "device_id": "sustained",
                    "event_id": str(i),
                    "timestamp": start + i,
                    "hr": 140,
                    "spo2": 98,
                    "temperature": 36.7,
                    "activity": "rest",
                },
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["clinical_event_ready"], i == 10)
        cases = self.client.get("/api/cases", headers=h).json()
        self.assertEqual(len(cases), 1)
        r = self.client.post(
            "/api/auth/login",
            json={"email": "cardio@demo.local", "password": "Demo@12345"},
        )
        card = {"Authorization": "Bearer " + r.json()["token"]}
        self.assertIn(
            cases[0]["id"],
            [c["id"] for c in self.client.get("/api/cases", headers=card).json()],
        )

    def test_impact_requires_stillness_before_case(self):
        h = self.patient()
        start = time.time() - 5
        for i in range(4):
            r = self.client.post(
                "/api/devices/ingest",
                headers=h,
                json={
                    "kind": "event",
                    "event": "fall",
                    "device_id": "fall-fixture",
                    "event_id": str(i),
                    "timestamp": start + i,
                    "acceleration": 3.6 if i == 0 else 0.05,
                },
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["fall_detected"], i == 3)
        self.assertEqual(len(self.client.get("/api/cases", headers=h).json()), 1)

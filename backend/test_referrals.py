import secrets
import unittest
from datetime import timedelta

from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.main import app, india_now
from backend.referrals import haversine


class ReferralTests(unittest.TestCase):
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
                "email": secrets.token_hex(6) + "@referral.test",
                "name": "Referral QA",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_haversine_known_distances(self):
        self.assertEqual(haversine(0, 0, 0, 0), 0)
        self.assertAlmostEqual(haversine(0, 0, 0, 1), 111.1949, places=3)

    def test_combined_distance_and_specialty_filter(self):
        r = self.client.get(
            "/api/doctors?latitude=19.076&longitude=72.8777&radius_km=50&specialty=General&language=Hindi",
            headers=self.patient(),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json())
        self.assertTrue(
            all(d["city"] == "Mumbai" and d["distance_km"] <= 50 for d in r.json())
        )
        self.assertTrue(all(not d["verified"] for d in r.json()))

    def test_invalid_partial_coordinates(self):
        self.assertEqual(
            self.client.get(
                "/api/doctors?latitude=20", headers=self.patient()
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                "/api/doctors?latitude=100&longitude=0", headers=self.patient()
            ).status_code,
            422,
        )

    def test_blocked_slot_cannot_book_then_reopens(self):
        doctor = self.login("doctor@demo.local")
        patient = self.patient()
        day = (india_now() + timedelta(days=6)).date().isoformat()
        slot = day + "T14:30"
        body = {
            "doctor_id": 1,
            "slot": slot,
            "reason": "Clinic unavailable for local testing",
        }
        self.assertEqual(
            self.client.post(
                "/api/clinician/blocked-slots", headers=doctor, json=body
            ).status_code,
            200,
        )
        self.assertNotIn(
            slot,
            self.client.get("/api/doctors/1/slots?day=" + day, headers=patient).json()[
                "slots"
            ],
        )
        self.assertEqual(
            self.client.post(
                "/api/appointments",
                headers=patient,
                json={"doctor_id": 1, "slot": slot},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                "/api/clinician/reopen-slot", headers=doctor, json=body
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/appointments",
                headers=patient,
                json={"doctor_id": 1, "slot": slot},
            ).status_code,
            200,
        )

    def test_schedule_assignment(self):
        doctor = self.login("doctor@demo.local")
        day = (india_now() + timedelta(days=7)).date().isoformat()
        self.assertEqual(
            self.client.post(
                "/api/clinician/blocked-slots",
                headers=doctor,
                json={
                    "doctor_id": 2,
                    "slot": day + "T10:00",
                    "reason": "Wrong clinician profile",
                },
            ).status_code,
            403,
        )

    def test_selected_appointment_clinician_gets_consented_original(self):
        patient = self.patient()
        cardio = self.login("cardio@demo.local")
        upload = self.client.post(
            "/api/reports/upload",
            headers=patient,
            files={"file": ("shared.txt", b"TSH: 2.1 mIU/L")},
        ).json()
        identity = upload["document_id"]
        url = "/api/reports/documents/" + str(identity)
        self.assertEqual(self.client.get(url, headers=cardio).status_code, 403)
        slot = (india_now() + timedelta(days=8)).date().isoformat() + "T15:30"
        self.assertEqual(
            self.client.post(
                "/api/appointments",
                headers=patient,
                json={"doctor_id": 2, "slot": slot, "share": True},
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get(url, headers=cardio).status_code, 200)
        appointment = self.client.get("/api/appointments", headers=patient).json()[0]
        self.client.post(
            "/api/appointments/" + str(appointment["id"]) + "/cancel", headers=patient
        )
        self.assertEqual(self.client.get(url, headers=cardio).status_code, 403)

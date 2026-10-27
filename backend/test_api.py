import os
import tempfile
import unittest

test_dir = tempfile.TemporaryDirectory()
os.environ["MEDIASSIST_DB"] = os.path.join(test_dir.name, "test.db")
from fastapi.testclient import TestClient

from backend.main import app, parse_report, triage


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()
        cls.patient = cls.signin("patient@demo.local")
        cls.doctor = cls.signin("doctor@demo.local")

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    @classmethod
    def signin(cls, email):
        r = cls.client.post(
            "/api/auth/login", json={"email": email, "password": "Demo@12345"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_auth_required(self):
        self.assertEqual(self.client.get("/api/cases").status_code, 401)

    def test_invalid_login(self):
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={"email": "patient@demo.local", "password": "bad"},
            ).status_code,
            401,
        )

    def test_patient_cannot_review(self):
        r = self.client.post(
            "/api/cases/1/review",
            headers=self.patient,
            json={"action": "approved", "note": "Review note"},
        )
        self.assertEqual(r.status_code, 403)

    def test_emergency_bypass(self):
        self.assertEqual(triage("chest pain", 2, 30)["urgency"], "EMERGENCY")
        r = self.client.post(
            "/api/symptoms",
            headers=self.patient,
            json={"symptoms": "chest pain", "severity": 2},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["urgency"], "EMERGENCY")

    def test_review_workflow(self):
        self.client.post(
            "/api/symptoms",
            headers=self.patient,
            json={"symptoms": "Cough for two days"},
        )
        case = self.client.get("/api/cases", headers=self.doctor).json()[0]
        r = self.client.post(
            f"/api/cases/{case['id']}/review",
            headers=self.doctor,
            json={
                "action": "needs_info",
                "note": "Please confirm the duration and associated symptoms.",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            any(
                "needs_info" in a["action"]
                for a in self.client.get("/api/audit", headers=self.doctor).json()
            )
        )

    def test_ingestion_validation_and_dedup(self):
        payload = {"hr": 70, "spo2": 98, "temperature": 36.8, "event_id": "dedup-test"}
        self.assertEqual(
            self.client.post(
                "/api/vitals", headers=self.patient, json=payload
            ).status_code,
            200,
        )
        self.assertTrue(
            self.client.post("/api/vitals", headers=self.patient, json=payload).json()[
                "duplicate"
            ]
        )
        self.assertEqual(
            self.client.post(
                "/api/vitals", headers=self.patient, json={**payload, "spo2": 150}
            ).status_code,
            422,
        )

    def test_all_scenarios(self):
        for scenario in [
            "normal_rest",
            "arrhythmia_episode",
            "low_spo2",
            "fever",
            "fall",
            "leads_off",
        ]:
            self.assertEqual(
                self.client.post(
                    "/api/simulator", headers=self.patient, json={"scenario": scenario}
                ).status_code,
                200,
            )
        queue = self.client.get("/api/cases", headers=self.patient).json()
        self.assertTrue(any(c["source"] == "device_event" for c in queue))

    def test_lab_values_and_units(self):
        rows = parse_report("Hemoglobin: 11.2 g/dL\nGlucose: 5.2 mmol/L")
        self.assertEqual(rows[0]["value"], 11.2)
        self.assertEqual(rows[0]["flag"], "low")
        self.assertEqual(rows[1]["flag"], "unit needs review")

    def test_disconnected_sensor_does_not_store_vitals(self):
        before = len(self.client.get("/api/vitals", headers=self.patient).json())
        r = self.client.post(
            "/api/simulator", headers=self.patient, json={"scenario": "leads_off"}
        )
        self.assertFalse(r.json()["signal"])
        self.assertEqual(
            len(self.client.get("/api/vitals", headers=self.patient).json()), before
        )

    def test_report_upload(self):
        r = self.client.post(
            "/api/reports/upload",
            headers=self.patient,
            files={"file": ("lab.txt", b"TSH: 2.1 mIU/L", "text/plain")},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["values"][0]["value"], 2.1)

    def test_booking_conflict(self):
        from datetime import timedelta

        from backend.main import india_now

        day = (india_now() + timedelta(days=2)).date().isoformat()
        payload = {"doctor_id": 1, "slot": day + "T10:00", "share": False}
        self.assertEqual(
            self.client.post(
                "/api/appointments", headers=self.patient, json=payload
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/appointments", headers=self.patient, json=payload
            ).status_code,
            409,
        )

    def test_seed_directory(self):
        self.assertEqual(
            len(self.client.get("/api/doctors", headers=self.patient).json()), 30
        )
        self.assertTrue(
            all(
                d["city"] == "Mumbai"
                for d in self.client.get(
                    "/api/doctors?city=Mumbai", headers=self.patient
                ).json()
            )
        )

    def test_isolation_consent_export_erase(self):
        r = self.client.post(
            "/api/auth/register",
            json={
                "email": "other@example.test",
                "name": "Other Patient",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        self.assertEqual(r.status_code, 200)
        headers = {"Authorization": "Bearer " + r.json()["token"]}
        self.assertEqual(self.client.get("/api/cases", headers=headers).json(), [])
        self.assertEqual(
            self.client.get("/api/me/export", headers=headers).json()["records"], []
        )
        self.client.put("/api/me/consent", headers=headers, json={"consent": False})
        self.assertEqual(
            self.client.post(
                "/api/symptoms", headers=headers, json={"symptoms": "cough"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete("/api/me", headers=headers).status_code, 200
        )
        self.assertEqual(self.client.get("/api/me", headers=headers).status_code, 401)


if __name__ == "__main__":
    unittest.main()

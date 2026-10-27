import secrets
import time
import unittest

from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.main import app, db
from backend.review_workflow import expire_pending


class FollowupTests(unittest.TestCase):
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
                "name": "Followup Fixture",
                "email": secrets.token_hex(8) + "@followup.test",
                "password": "Demo@12345",
                "consent": True,
            },
        )
        return {"Authorization": "Bearer " + r.json()["token"]}

    def doctor(self):
        r = self.client.post(
            "/api/auth/login",
            json={"email": "doctor@demo.local", "password": "Demo@12345"},
        )
        return {"Authorization": "Bearer " + r.json()["token"]}

    def request(self, header, action="needs_info"):
        result = self.client.post(
            "/api/symptoms",
            headers=header,
            json={"symptoms": "fictional cough", "severity": 4},
        ).json()
        identity = result["case_id"]
        doctor = self.doctor()
        self.assertEqual(
            self.client.post(
                "/api/cases/" + str(identity) + "/review",
                headers=doctor,
                json={
                    "action": action,
                    "note": "Please clarify the fictional symptom duration.",
                },
            ).status_code,
            200,
        )
        return identity, doctor

    def test_reply_preserves_original_and_requeues_for_assigned_doctor(self):
        h = self.patient()
        identity, doctor = self.request(h)
        url = "/api/cases/" + str(identity)
        before = self.client.get(url, headers=doctor).json()["original"]
        reply = self.client.post(
            url + "/followup",
            headers=h,
            json={"text": "Fictional clarification for three days."},
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertIsNone(reply.json()["emergency"])
        after = self.client.get(url, headers=doctor).json()
        self.assertEqual(after["status"], "pending")
        self.assertEqual(after["original"], before)
        self.assertEqual(
            after["followups"][0]["text"], "Fictional clarification for three days."
        )
        self.assertEqual(
            self.client.post(
                url + "/followup", headers=h, json={"text": "Repeated reply"}
            ).status_code,
            409,
        )

    def test_owner_and_consent_scope(self):
        h = self.patient()
        identity, _ = self.request(h)
        url = "/api/cases/" + str(identity) + "/followup"
        self.assertEqual(
            self.client.post(
                url, headers=self.patient(), json={"text": "Wrong patient"}
            ).status_code,
            404,
        )
        self.client.put("/api/me/consent", headers=h, json={"consent": False})
        self.assertEqual(
            self.client.post(
                url, headers=h, json={"text": "Paused processing"}
            ).status_code,
            403,
        )

    def test_emergency_reply_bypasses_waiting(self):
        h = self.patient()
        identity, _ = self.request(h)
        result = self.client.post(
            "/api/cases/" + str(identity) + "/followup",
            headers=h,
            json={"text": "I now have chest pain"},
        ).json()
        self.assertEqual(result["emergency"]["urgency"], "EMERGENCY")
        cases = self.client.get("/api/cases", headers=h).json()
        self.assertTrue(any(c["urgency"] == "EMERGENCY" for c in cases))

    def test_requeue_has_new_timeout_clock_without_changing_event_time(self):
        h = self.patient()
        identity, _ = self.request(h)
        old = time.time() - 90000
        with db() as c:
            c.execute("UPDATE cases SET created=? WHERE id=?", (old, identity))
        self.client.post(
            "/api/cases/" + str(identity) + "/followup",
            headers=h,
            json={"text": "Fictional clarification supplied today"},
        )
        expire_pending()
        with db() as c:
            case = c.execute("SELECT * FROM cases WHERE id=?", (identity,)).fetchone()
        self.assertEqual(case["status"], "pending")
        self.assertEqual(case["created"], old)

    def test_review_outcome_is_not_falsely_displayed_as_awaiting(self):
        for action, phrase in [
            ("needs_info", "requested more information"),
            ("rejected", "did not approve"),
            ("escalated", "escalated"),
        ]:
            h = self.patient()
            identity, _ = self.request(h, action)
            assessment = self.client.get(
                "/api/cases/" + str(identity), headers=h
            ).json()["original"]
            self.assertIn(phrase, assessment["guidance"])
            self.assertEqual(assessment["possibilities"], [])
            self.assertIn("clarify", assessment["doctor_note"])

    def test_empty_reply_is_rejected(self):
        h = self.patient()
        identity, _ = self.request(h)
        self.assertEqual(
            self.client.post(
                "/api/cases/" + str(identity) + "/followup",
                headers=h,
                json={"text": "   "},
            ).status_code,
            422,
        )

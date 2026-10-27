import secrets
import unittest

from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.main import app


class ConversationTests(unittest.TestCase):
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
                "email": secrets.token_hex(6) + "@chat.test",
                "name": "Conversation QA",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_full_followup_and_held_assessment(self):
        h = self.patient()
        session = self.client.post("/api/conversations", headers=h, json={}).json()
        for field, text in [
            ("symptoms", "cough for two days"),
            ("age", "35"),
            ("duration", "2 days"),
            ("severity", "4"),
            ("associated", "sore throat"),
            ("conditions", "none"),
        ]:
            self.assertEqual(session["question"]["field"], field)
            response = self.client.post(
                "/api/conversations/" + session["id"] + "/answer",
                headers=h,
                json={"text": text, "field": field},
            )
            self.assertEqual(response.status_code, 200, response.text)
            session = response.json()
        self.assertTrue(session["complete"])
        self.assertTrue(session["assessment"]["pending_review"])
        self.assertEqual(session["assessment"]["ranked_conditions"], [])
        self.assertEqual(session["fields"]["age"], 35)
        self.assertEqual(session["fields"]["conditions"], "none")

    def test_red_flags_bypass_followups(self):
        h = self.patient()
        result = self.client.post(
            "/api/conversations", headers=h, json={"text": "chest pain"}
        ).json()
        self.assertTrue(result["complete"])
        self.assertEqual(result["assessment"]["urgency"], "EMERGENCY")
        self.assertFalse(result["assessment"]["pending_review"])

    def test_red_flag_during_age_question(self):
        h = self.patient()
        session = self.client.post(
            "/api/conversations", headers=h, json={"text": "cough"}
        ).json()
        r = self.client.post(
            "/api/conversations/" + session["id"] + "/answer",
            headers=h,
            json={"text": "I now have chest pain"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["assessment"]["urgency"], "EMERGENCY")

    def test_answer_validation_and_isolation(self):
        h = self.patient()
        other = self.patient()
        session = self.client.post(
            "/api/conversations", headers=h, json={"text": "cough"}
        ).json()
        self.assertEqual(
            self.client.get(
                "/api/conversations/" + session["id"], headers=other
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/api/conversations/" + session["id"] + "/answer",
                headers=h,
                json={"text": "0", "field": "age"},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/api/conversations/" + session["id"] + "/answer",
                headers=h,
                json={"text": "30", "field": "severity"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.get("/api/conversations", headers=h).json()[0]["id"],
            session["id"],
        )

    def test_local_model_hypotheses_stay_held_until_assigned_approval(self):
        from unittest.mock import patch

        h = self.patient()
        session = self.client.post("/api/conversations", headers=h, json={}).json()
        hypothesis = [
            {
                "name": "Fictional candidate",
                "rationale": "Fictional schema test, not medical advice.",
                "rank": 1,
            }
        ]
        with patch("backend.assessment_model.hypotheses", return_value=hypothesis):
            for text in ["fictional mild cough", "35", "2 days", "4", "none", "none"]:
                session = self.client.post(
                    "/api/conversations/" + session["id"] + "/answer",
                    headers=h,
                    json={"text": text},
                ).json()
        assessment = session["assessment"]
        self.assertTrue(assessment["pending_review"])
        self.assertEqual(assessment["ranked_conditions"], [])
        token = self.client.post(
            "/api/auth/login",
            json={"email": "doctor@demo.local", "password": "Demo@12345"},
        ).json()["token"]
        doctor = {"Authorization": "Bearer " + token}
        review = self.client.post(
            "/api/cases/" + str(assessment["case_id"]) + "/review",
            headers=doctor,
            json={"action": "approved", "note": "Fictional schema review only."},
        )
        self.assertEqual(review.status_code, 200)
        released = self.client.get(
            "/api/conversations/" + session["id"], headers=h
        ).json()["assessment"]
        self.assertEqual(released["ranked_conditions"], hypothesis)
        self.assertEqual(released["urgency"], "CONSULT_SOON")

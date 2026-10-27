import secrets
import unittest

from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.main import app, db, init


class FoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def login(self, email):
        result = self.client.post(
            "/api/auth/login", json={"email": email, "password": "Demo@12345"}
        )
        self.assertEqual(result.status_code, 200, result.text)
        return {"Authorization": "Bearer " + result.json()["token"]}

    def patient(self):
        result = self.client.post(
            "/api/auth/register",
            json={
                "email": secrets.token_hex(6) + "@test.local",
                "name": "Phase One",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        return {"Authorization": "Bearer " + result.json()["token"]}

    def case(self):
        p = self.patient()
        self.client.post(
            "/api/symptoms", headers=p, json={"symptoms": "cough for two days"}
        )
        return self.client.get("/api/cases", headers=p).json()[0]

    def test_two_clinician_accounts(self):
        for email in ["doctor@demo.local", "cardio@demo.local"]:
            h = self.login(email)
            self.assertEqual(
                self.client.get("/api/me", headers=h).json()["role"], "doctor"
            )

    def test_logout_revokes_only_the_current_session(self):
        one = self.login("patient@demo.local")
        two = self.login("patient@demo.local")
        self.assertEqual(
            self.client.post("/api/auth/logout", headers=one).status_code, 200
        )
        self.assertEqual(self.client.get("/api/me", headers=one).status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers=two).status_code, 200)

    def test_admin_cannot_approve(self):
        case = self.case()
        response = self.client.post(
            "/api/cases/" + str(case["id"]) + "/review",
            headers=self.login("admin@demo.local"),
            json={
                "action": "approved",
                "note": "An administrator must not clinically approve",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_cardiologist_cannot_read_or_review_gp_case(self):
        case = self.case()
        h = self.login("cardio@demo.local")
        self.assertEqual(
            self.client.get("/api/cases/" + str(case["id"]), headers=h).status_code, 404
        )
        self.assertFalse(
            any(
                r["id"] == case["id"]
                for r in self.client.get("/api/cases", headers=h).json()
            )
        )
        self.assertEqual(
            self.client.post(
                "/api/cases/" + str(case["id"]) + "/review",
                headers=h,
                json={"action": "approved", "note": "Wrong clinician must be rejected"},
            ).status_code,
            403,
        )

    def test_migration_is_idempotent(self):
        init()
        init()
        with db() as c:
            self.assertGreaterEqual(
                c.execute("SELECT COUNT(*) FROM schema_versions").fetchone()[0], 1
            )
            self.assertEqual(
                c.execute(
                    "SELECT COUNT(*) FROM users WHERE email='cardio@demo.local'"
                ).fetchone()[0],
                1,
            )

    def test_auth_throttle_is_bounded(self):
        from backend.security import _attempts

        email = secrets.token_hex(6) + "@invalid.test"
        for _ in range(8):
            self.assertEqual(
                self.client.post(
                    "/api/auth/login", json={"email": email, "password": "wrong"}
                ).status_code,
                401,
            )
        self.assertEqual(
            self.client.post(
                "/api/auth/login", json={"email": email, "password": "wrong"}
            ).status_code,
            429,
        )
        self.assertLessEqual(len(_attempts), 1024)

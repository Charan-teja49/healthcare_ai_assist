import secrets
import time
import unittest
import urllib.error
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.lab_parser import parse
from backend.language import translate_template
from backend.main import app, db
from backend.notification_dispatch import dispatch_once, queue_emergency, sms_ready


async def idle(stop):
    await stop.wait()


TWILIO = {
    "SMS_PROVIDER": "twilio",
    "TWILIO_ACCOUNT_SID": "AC" + "a" * 32,
    "TWILIO_AUTH_TOKEN": "fictional-test-token",
    "TWILIO_FROM": "+15005550006",
}


class PhaseEightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = patch("backend.notification_dispatch.notification_worker", idle)
        cls.worker.start()
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        cls.worker.stop()

    def patient(self):
        r = self.client.post(
            "/api/auth/register",
            json={
                "name": "Phase Eight Fixture",
                "email": secrets.token_hex(8) + "@phase8.test",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        header = {"Authorization": "Bearer " + r.json()["token"]}
        return header, self.client.get("/api/me", headers=header).json()["id"]

    def contact(self, h, consent=True):
        return self.client.put(
            "/api/me/emergency-contact",
            headers=h,
            json={
                "name": "Fictional Contact",
                "phone": "+919876543210",
                "consent": consent,
            },
        )

    def latest(self, identity):
        with db() as c:
            return dict(
                c.execute(
                    "SELECT * FROM integration_outbox WHERE user_id=? ORDER BY id DESC",
                    (identity,),
                ).fetchone()
            )

    def queue(self, identity):
        with db() as c:
            queue_emergency(c, identity)

    def test_contact_validation_and_isolation(self):
        a, _ = self.patient()
        b, _ = self.patient()
        self.assertEqual(self.contact(a).status_code, 200)
        self.assertEqual(
            self.client.get("/api/me/emergency-contact", headers=b).json()["phone"], ""
        )
        self.assertEqual(
            self.client.put(
                "/api/me/emergency-contact",
                headers=a,
                json={"phone": "123", "consent": True},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.put(
                "/api/me/emergency-contact", headers=a, json={"consent": True}
            ).status_code,
            422,
        )

    def test_emergency_defaults_to_local_mock(self):
        h, identity = self.patient()
        with patch.dict("os.environ", {"SMS_PROVIDER": "console"}):
            self.client.post(
                "/api/symptoms", headers=h, json={"symptoms": "chest pain"}
            )
            row = self.latest(identity)
            self.assertEqual(row["status"], "mock")
            self.assertNotIn("chest pain", row["payload"])

    def test_configured_provider_requires_recipient_consent(self):
        h, identity = self.patient()
        self.contact(h, False)
        with patch.dict("os.environ", TWILIO):
            self.queue(identity)
        self.assertEqual(self.latest(identity)["status"], "mock")

    def test_consent_rechecked_before_delivery(self):
        h, identity = self.patient()
        self.contact(h)
        with patch.dict("os.environ", TWILIO):
            self.queue(identity)
            self.client.put("/api/me/consent", headers=h, json={"consent": False})
            sender = unittest.mock.Mock()
            dispatch_once(sender)
            self.assertEqual(self.latest(identity)["status"], "cancelled")
            sender.assert_not_called()

    def test_contact_change_cancels_old_queue(self):
        h, identity = self.patient()
        self.contact(h)
        with patch.dict("os.environ", TWILIO):
            self.queue(identity)
        self.contact(h, False)
        self.assertEqual(self.latest(identity)["status"], "cancelled")

    def test_provider_acceptance_not_claimed_as_delivered(self):
        h, identity = self.patient()
        self.contact(h)
        with patch.dict("os.environ", TWILIO):
            self.assertTrue(sms_ready())
            self.queue(identity)
            dispatch_once(lambda phone, message: "SM" + "b" * 32)
        row = self.latest(identity)
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["attempts"], 1)

    def test_retry_stops_after_three_definite_rejections(self):
        h, identity = self.patient()
        self.contact(h)

        def reject(phone, message):
            raise urllib.error.HTTPError(
                "https://example.invalid", 503, "unavailable", None, None
            )

        with patch.dict("os.environ", TWILIO):
            self.queue(identity)
            for i in range(3):
                dispatch_once(reject)
                with db() as c:
                    c.execute(
                        "UPDATE integration_outbox SET next_attempt=0 WHERE user_id=?",
                        (identity,),
                    )
        self.assertEqual(self.latest(identity)["status"], "failed")
        self.assertEqual(self.latest(identity)["attempts"], 3)

    def test_timeout_is_not_blindly_retried(self):
        h, identity = self.patient()
        self.contact(h)

        def uncertain(phone, message):
            raise TimeoutError()

        with patch.dict("os.environ", TWILIO):
            self.queue(identity)
            dispatch_once(uncertain)
        self.assertEqual(self.latest(identity)["status"], "delivery_unknown")

    def test_push_setup_and_endpoint_validation(self):
        h, _ = self.patient()
        self.assertFalse(
            self.client.get("/api/notifications/push/config", headers=h).json()[
                "configured"
            ]
        )
        bad = {
            "endpoint": "https://localhost/admin",
            "keys": {"p256dh": "a" * 30, "auth": "b" * 20},
        }
        self.assertEqual(
            self.client.post(
                "/api/notifications/push/subscription", headers=h, json=bad
            ).status_code,
            422,
        )
        bad["endpoint"] = "https://fcm.googleapis.com/fake"
        self.assertEqual(
            self.client.post(
                "/api/notifications/push/subscription", headers=h, json=bad
            ).status_code,
            503,
        )

    def test_hindi_questions_and_emergency_bypass(self):
        h, _ = self.patient()
        session = self.client.post(
            "/api/conversations", headers=h, json={"language": "hi"}
        ).json()
        self.assertIn("लक्षण", session["question"]["text"])
        r = self.client.post(
            "/api/conversations/" + session["id"] + "/answer",
            headers=h,
            json={"text": "सीने में दर्द", "field": "symptoms"},
        )
        self.assertEqual(r.json()["assessment"]["urgency"], "EMERGENCY")
        self.assertIn("आपातकालीन", r.json()["assessment"]["guidance"])

    def test_translation_cache_rejects_health_text(self):
        h, _ = self.patient()
        translate_template.cache_clear()
        for i in range(3):
            self.assertIn(
                "लक्षण",
                translate_template("Describe the symptoms you are experiencing.", "hi"),
            )
        self.assertEqual(translate_template.cache_info().hits, 2)
        self.assertEqual(
            self.client.post(
                "/api/language/template",
                headers=h,
                json={"text": "my private health text", "language": "hi"},
            ).status_code,
            422,
        )

    def test_all_six_demo_scenarios_under_three_minutes(self):
        h, _ = self.patient()
        started = time.monotonic()
        for name in [
            "normal_rest",
            "arrhythmia_episode",
            "low_spo2",
            "fever",
            "fall",
            "leads_off",
        ]:
            r = self.client.post("/api/demo/replay", headers=h, json={"scenario": name})
            self.assertEqual(r.status_code, 200, r.text)
            data = r.json()
            self.assertTrue(data["synthetic"])
            if name in ("arrhythmia_episode", "low_spo2", "fever", "fall"):
                self.assertTrue(data["new_cases"], name)
            else:
                self.assertEqual(data["new_cases"], [], name)
            if name == "fall":
                self.assertTrue(data["fall_detected"])
            if name == "leads_off":
                self.assertFalse(data["final"]["signal"])
                self.assertNotIn("hr", data["final"])
        self.assertLess(time.monotonic() - started, 180)

    def test_invalid_demo_and_consent_rejection(self):
        h, _ = self.patient()
        self.assertEqual(
            self.client.post(
                "/api/demo/replay", headers=h, json={"scenario": "unknown"}
            ).status_code,
            422,
        )
        self.client.put("/api/me/consent", headers=h, json={"consent": False})
        self.assertEqual(
            self.client.post(
                "/api/demo/replay", headers=h, json={"scenario": "normal_rest"}
            ).status_code,
            403,
        )

    def test_unknown_unit_or_reversed_interval_never_silently_normal(self):
        for text in [
            "Glucose: 5.2 bananas reference: 3.9-5.5",
            "Glucose: 108 mg/dL range 120-70",
        ]:
            self.assertIn("needs review", parse(text)[0]["flag"])

    def test_doctor_audit_is_actor_scoped(self):
        def login(email):
            return {
                "Authorization": "Bearer "
                + self.client.post(
                    "/api/auth/login", json={"email": email, "password": "Demo@12345"}
                ).json()["token"]
            }

        d = login("doctor@demo.local")
        c = login("cardio@demo.local")
        own = self.client.get("/api/me", headers=d).json()["id"]
        self.client.post("/api/auth/logout", headers=c)
        rows = self.client.get("/api/audit", headers=d).json()
        self.assertTrue(all(r["actor"] == own for r in rows))

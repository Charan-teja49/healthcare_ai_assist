"""Field and workflow regression tests. All data is in a temporary database."""

import asyncio
import io
import json
import secrets
import time
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.main import app, db, india_now, init, parse_report, stream


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()
        cls.patient = cls.login("patient@demo.local")
        cls.doctor = cls.login("doctor@demo.local")
        cls.admin = cls.login("admin@demo.local")

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    @classmethod
    def login(cls, email):
        r = cls.client.post(
            "/api/auth/login", json={"email": email, "password": "Demo@12345"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}

    def new_patient(self, **changes):
        body = {
            "email": secrets.token_hex(6) + "@test.local",
            "password": "TestPassword123",
            "name": "New Patient",
            "consent": True,
            **changes,
        }
        r = self.client.post("/api/auth/register", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]

    def future(self, days=3, time="11:00"):
        return (india_now() + timedelta(days=days)).date().isoformat() + "T" + time

    def post(self, path, body, headers=None):
        return self.client.post(
            "/api" + path, headers=headers or self.patient, json=body
        )

    def test_registration_each_field(self):
        valid = {
            "email": "valid@test.local",
            "password": "LongPass123",
            "name": "Test User",
            "consent": True,
        }
        for field, value in [
            ("email", "not-an-email"),
            ("email", "a@b"),
            ("email", "a b@c.test"),
            ("password", "short"),
            ("name", "  "),
            ("name", "A"),
            ("consent", False),
        ]:
            with self.subTest(field=field, value=value):
                self.assertEqual(
                    self.post("/auth/register", {**valid, field: value}).status_code,
                    422,
                )

    def test_duplicate_registration(self):
        headers, user = self.new_patient()
        self.assertEqual(
            self.post(
                "/auth/register",
                {
                    "email": user["email"],
                    "password": "LongPass123",
                    "name": "Another",
                    "consent": True,
                },
            ).status_code,
            409,
        )

    def test_registration_role_injection_cannot_create_doctor(self):
        headers, user = self.new_patient(role="doctor")
        self.assertEqual(user["role"], "patient")
        self.assertEqual(
            self.client.get("/api/audit", headers=headers).status_code, 403
        )

    def test_login_case_and_password_exactness(self):
        self.assertEqual(
            self.post(
                "/auth/login",
                {"email": " PATIENT@DEMO.LOCAL ", "password": "Demo@12345"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.post(
                "/auth/login",
                {"email": "patient@demo.local", "password": " Demo@12345"},
            ).status_code,
            401,
        )

    def test_bad_and_expired_tokens(self):
        import jwt

        from backend.main import SECRET

        for token in [
            "invalid",
            jwt.encode({"sub": "1", "exp": 1}, SECRET, algorithm="HS256"),
        ]:
            self.assertEqual(
                self.client.get(
                    "/api/me", headers={"Authorization": "Bearer " + token}
                ).status_code,
                401,
            )

    def test_symptom_fields(self):
        valid = {"symptoms": "Cough", "duration": "2 days", "age": 30, "severity": 4}
        for field, value in [
            ("symptoms", "  "),
            ("symptoms", "a"),
            ("symptoms", "x" * 3001),
            ("duration", " "),
            ("duration", "x" * 101),
            ("age", 0),
            ("age", 121),
            ("age", 1.5),
            ("severity", 0),
            ("severity", 11),
            ("severity", 1.5),
        ]:
            with self.subTest(field=field, value=str(value)[:30]):
                self.assertEqual(
                    self.post("/symptoms", {**valid, field: value}).status_code, 422
                )
        for age in [1, 120]:
            self.assertEqual(
                self.post("/symptoms", {**valid, "age": age}).status_code, 200
            )

    def test_symptom_emergency_and_nonemergency(self):
        for text in [
            "chest pain",
            "cannot breathe",
            "severe bleeding",
            "unconscious",
            "face droop",
        ]:
            self.assertEqual(
                self.post("/symptoms", {"symptoms": text}).json()["urgency"],
                "EMERGENCY",
            )
        self.assertEqual(
            self.post("/symptoms", {"symptoms": "itchy rash", "severity": 8}).json()[
                "urgency"
            ],
            "URGENT",
        )
        self.assertEqual(
            self.post("/symptoms", {"symptoms": "itchy rash"}).json()["specialist"],
            "Dermatology",
        )

    def test_withdraw_and_restore_consent_all_health_writes(self):
        headers, user = self.new_patient()
        self.client.put("/api/me/consent", headers=headers, json={"consent": False})
        for path, body in [
            ("/symptoms", {"symptoms": "cough"}),
            ("/reports", {"text": "Glucose: 90 mg/dL"}),
            ("/vitals", {"hr": 72, "spo2": 98, "temperature": 37, "event_id": "x"}),
            ("/simulator", {"scenario": "normal_rest"}),
            ("/appointments", {"doctor_id": 1, "slot": self.future(), "share": True}),
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.post(path, body, headers).status_code, 403)
        self.assertEqual(
            self.client.get("/api/doctors", headers=headers).status_code, 200
        )
        self.client.put("/api/me/consent", headers=headers, json={"consent": True})
        self.assertEqual(
            self.post("/symptoms", {"symptoms": "cough"}, headers).status_code, 200
        )

    def test_stream_revoked_consent_stops(self):
        headers, user = self.new_patient()
        with db() as c:
            c.execute("UPDATE users SET consent=0 WHERE id=?", (user["id"],))

        async def check():
            response = await stream("normal_rest", user)
            return await anext(response.body_iterator)

        self.assertIn("consent_required", asyncio.run(check()))

    def test_vital_each_bound(self):
        valid = {"hr": 72, "spo2": 98, "temperature": 36.7, "event_id": "field-test"}
        for field, value in [
            ("hr", 24),
            ("hr", 251),
            ("spo2", 49),
            ("spo2", 101),
            ("temperature", 29),
            ("temperature", 46),
            ("event_id", " "),
            ("device_id", " "),
        ]:
            with self.subTest(field=field, value=value):
                self.assertEqual(
                    self.post("/vitals", {**valid, field: value}).status_code, 422
                )

    def test_vital_nonfinite_rejected(self):
        # JSON string numeric conversion must not allow infinity into storage.
        self.assertEqual(
            self.post(
                "/vitals",
                {
                    "hr": "Infinity",
                    "spo2": 98,
                    "temperature": 37,
                    "event_id": "infinity",
                },
            ).status_code,
            422,
        )
        r = self.client.post(
            "/api/vitals",
            headers={**self.patient, "Content-Type": "application/json"},
            content='{"hr":NaN,"spo2":98,"temperature":37,"event_id":"nan"}',
        )
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("input", r.json()["detail"][0])

    def test_baseline_and_alert_coalescing(self):
        headers, user = self.new_patient()
        for i in range(11):
            r = self.post(
                "/vitals",
                {"hr": 72, "spo2": 98, "temperature": 36.7, "event_id": str(i)},
                headers,
            )
            self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["baseline_ready"])
        for i in range(2):
            r = self.post(
                "/vitals",
                {
                    "hr": 110,
                    "spo2": 98,
                    "temperature": 36.7,
                    "event_id": "deviation" + str(i),
                },
                headers,
            )
            self.assertTrue(r.json()["baseline_deviation"])
        queue = self.client.get("/api/cases", headers=headers).json()
        self.assertEqual(len(queue), 1)

    def test_persistent_dedup_device_scope(self):
        headers, user = self.new_patient()
        payload = {
            "hr": 72,
            "spo2": 98,
            "temperature": 36.7,
            "event_id": "same",
            "device_id": "one",
        }
        self.assertEqual(self.post("/vitals", payload, headers).status_code, 200)
        self.assertTrue(self.post("/vitals", payload, headers).json()["duplicate"])
        self.assertNotIn(
            "duplicate",
            self.post("/vitals", {**payload, "device_id": "two"}, headers).json(),
        )

    def test_report_fields(self):
        for text in ["", "  ", "a", "x" * 30001]:
            self.assertEqual(self.post("/reports", {"text": text}).status_code, 422)
        self.assertEqual(
            self.post("/reports", {"text": "Unrecognised report content"}).json()[
                "values"
            ],
            [],
        )

    def test_report_units_no_prefix_false_positive(self):
        for raw in [
            "Glucose: 6 mmol/L",
            "Glucose: 90 mg/dLWRONG",
            "Glucose: -5 mg/dL",
            "Glucose: 90",
        ]:
            self.assertEqual(parse_report(raw)[0]["flag"], "unit needs review")
        self.assertEqual(
            parse_report("Glucose: 90 mg/dL (fasting)")[0]["flag"], "within demo range"
        )

    def test_report_preserves_values(self):
        r = self.post("/reports", {"text": "Hemoglobin: 11.27 g/dL\nTSH: 4.13 mIU/L"})
        self.assertEqual([x["value"] for x in r.json()["values"]], [11.27, 4.13])

    def test_upload_bad_extension_empty_oversize_encrypted(self):
        files = [
            ("bad.exe", b"fake"),
            ("empty.txt", b""),
            ("scan.pdf", b"%PDF fake"),
            ("big.txt", b"x" * 5_000_001),
        ]
        for name, content in files:
            with self.subTest(name=name):
                r = self.client.post(
                    "/api/reports/upload",
                    headers=self.patient,
                    files={"file": (name, content)},
                )
                self.assertEqual(r.status_code, 413 if name == "big.txt" else 422)
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("secret")
        buffer = io.BytesIO()
        writer.write(buffer)
        self.assertEqual(
            self.client.post(
                "/api/reports/upload",
                headers=self.patient,
                files={"file": ("locked.pdf", buffer.getvalue())},
            ).status_code,
            422,
        )

    def test_ocr_missing_setup_and_adapter(self):
        with patch("backend.integrations.tesseract_path", return_value=None):
            r = self.client.post(
                "/api/reports/upload",
                headers=self.patient,
                files={"file": ("scan.png", b"\x89PNG\r\n\x1a\n")},
            )
            self.assertEqual(r.status_code, 503)
        with patch(
            "backend.integrations.extract_image_text", return_value="Glucose: 90 mg/dL"
        ):
            r = self.client.post(
                "/api/reports/upload",
                headers=self.patient,
                files={"file": ("scan.png", b"fake")},
            )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["values"][0]["value"], 90)

    def test_pdf_text_extraction(self):
        # Minimal real PDF fixture with a text object and correct xref offsets.
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        content = b"BT /F1 12 Tf 20 250 Td (Glucose: 95 mg/dL) Tj ET"
        objects.append(
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
        pdf = b"%PDF-1.4\n"
        offsets = [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(pdf))
            pdf += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
        xref = len(pdf)
        pdf += (
            b"xref\n0 6\n0000000000 65535 f \n"
            + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets[1:])
            + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
        )
        r = self.client.post(
            "/api/reports/upload",
            headers=self.patient,
            files={"file": ("valid.pdf", pdf)},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["values"][0]["value"], 95)

    def test_directory_all_filters(self):
        r = self.client.get(
            "/api/doctors?city=Mumbai&specialty=General&language=Hindi",
            headers=self.patient,
        )
        self.assertTrue(r.json())
        self.assertTrue(
            all(
                x["city"] == "Mumbai"
                and x["specialty"] == "General physician"
                and "Hindi" in x["language"]
                for x in r.json()
            )
        )
        self.assertEqual(
            self.client.get("/api/doctors?city=Unknown", headers=self.patient).json(),
            [],
        )

    def test_slots_date_fields(self):
        for day in [
            "bad",
            "2026-02-30",
            (india_now() - timedelta(days=1)).date().isoformat(),
            (india_now() + timedelta(days=91)).date().isoformat(),
        ]:
            self.assertEqual(
                self.client.get(
                    "/api/doctors/1/slots", headers=self.patient, params={"day": day}
                ).status_code,
                422,
            )
        self.assertEqual(
            self.client.get(
                "/api/doctors/999/slots",
                headers=self.patient,
                params={"day": self.future().split("T")[0]},
            ).status_code,
            404,
        )

    def test_booking_fields_reject_midnight_and_invalid_slots(self):
        for slot in [
            self.future(time="00:30"),
            self.future(time="08:30"),
            self.future(time="18:00"),
            self.future(time="10:15"),
            self.future(days=-1),
            "not-a-date",
            "2026-02-30T10:00",
        ]:
            with self.subTest(slot=slot):
                self.assertEqual(
                    self.post(
                        "/appointments", {"doctor_id": 1, "slot": slot}
                    ).status_code,
                    422,
                )
        self.assertEqual(
            self.post(
                "/appointments", {"doctor_id": 0, "slot": self.future()}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.post(
                "/appointments", {"doctor_id": 999, "slot": self.future()}
            ).status_code,
            404,
        )

    def test_booking_slots_cancel_and_rebook(self):
        headers, user = self.new_patient()
        slot = self.future(days=4, time="14:30")
        payload = {"doctor_id": 2, "slot": slot, "share": True}
        self.assertEqual(self.post("/appointments", payload, headers).status_code, 200)
        remaining = self.client.get(
            "/api/doctors/2/slots", headers=headers, params={"day": slot[:10]}
        ).json()["slots"]
        self.assertNotIn(slot, remaining)
        appointment = self.client.get("/api/appointments", headers=headers).json()[0]
        self.assertEqual(
            self.post(
                f"/appointments/{appointment['id']}/cancel", {}, headers
            ).status_code,
            200,
        )
        self.assertEqual(self.post("/appointments", payload, headers).status_code, 200)
        after = self.client.get("/api/appointments", headers=headers).json()
        self.assertEqual(len(after), 2)
        self.assertEqual(sorted(a["status"] for a in after), ["booked", "cancelled"])

    def test_appointment_cancellation_isolation(self):
        headers, user = self.new_patient()
        other, _ = self.new_patient()
        self.post(
            "/appointments",
            {"doctor_id": 3, "slot": self.future(time="15:00")},
            headers,
        )
        appointment = self.client.get("/api/appointments", headers=headers).json()[0]
        self.assertEqual(
            self.post(
                f"/appointments/{appointment['id']}/cancel", {}, other
            ).status_code,
            404,
        )

    def test_clinician_shared_records_double_consent(self):
        headers, user = self.new_patient()
        self.post("/reports", {"text": "Glucose: 95 mg/dL"}, headers)
        self.post(
            "/appointments",
            {"doctor_id": 4, "slot": self.future(time="16:00"), "share": True},
            headers,
        )
        appointment = self.client.get("/api/appointments", headers=headers).json()[0]
        url = f"/api/appointments/{appointment['id']}/shared-records"
        self.assertEqual(self.client.get(url, headers=headers).status_code, 403)
        self.assertTrue(self.client.get(url, headers=self.doctor).json())
        self.client.put("/api/me/consent", headers=headers, json={"consent": False})
        self.assertEqual(self.client.get(url, headers=self.doctor).status_code, 403)

    def test_no_appointment_sharing_without_checkbox(self):
        headers, user = self.new_patient()
        self.post(
            "/appointments",
            {"doctor_id": 5, "slot": self.future(time="16:30"), "share": False},
            headers,
        )
        a = self.client.get("/api/appointments", headers=headers).json()[0]
        self.assertEqual(
            self.client.get(
                f"/api/appointments/{a['id']}/shared-records", headers=self.doctor
            ).status_code,
            403,
        )

    def test_case_original_data_and_isolation(self):
        headers, user = self.new_patient()
        other, _ = self.new_patient()
        self.post("/reports", {"text": "Glucose: 95 mg/dL"}, headers)
        case = self.client.get("/api/cases", headers=headers).json()[0]
        url = f"/api/cases/{case['id']}"
        self.assertEqual(self.client.get(url, headers=other).status_code, 404)
        self.assertEqual(
            self.client.get(url, headers=self.doctor).json()["original"]["values"][0][
                "value"
            ],
            95,
        )

    def test_review_fields_all_actions(self):
        headers, user = self.new_patient()
        self.post("/symptoms", {"symptoms": "cough"}, headers)
        case = self.client.get("/api/cases", headers=headers).json()[0]
        path = f"/cases/{case['id']}/review"
        for note, action in [
            ("    ", "approved"),
            ("abcd", "approved"),
            ("x" * 2001, "approved"),
            ("Valid note", "invalid"),
        ]:
            self.assertEqual(
                self.post(
                    path, {"note": note, "action": action}, self.doctor
                ).status_code,
                422,
            )
        for action in ["approved", "rejected", "needs_info", "escalated"]:
            self.assertEqual(
                self.post(
                    path,
                    {"note": "Clinician follow-up note", "action": action},
                    self.doctor,
                ).status_code,
                200,
            )
        self.assertEqual(
            self.post(
                "/cases/999999/review",
                {"note": "Valid note", "action": "approved"},
                self.doctor,
            ).status_code,
            404,
        )

    def test_review_timeout_fallback(self):
        headers, user = self.new_patient()
        self.post("/symptoms", {"symptoms": "cough"}, headers)
        with db() as c:
            c.execute(
                "UPDATE cases SET created=? WHERE user_id=?",
                (time.time() - 90000, user["id"]),
            )
        case = self.client.get("/api/cases", headers=headers).json()[0]
        self.assertEqual(case["status"], "timed_out")
        self.assertIn("in-person", case["review"])

    def test_notifications_ownership_and_mark_read(self):
        headers, user = self.new_patient()
        other, _ = self.new_patient()
        self.post("/symptoms", {"symptoms": "cough"}, headers)
        n = self.client.get("/api/notifications", headers=headers).json()[0]
        self.assertEqual(
            self.post(f"/notifications/{n['id']}/read", {}, other).status_code, 404
        )
        self.assertEqual(
            self.post(f"/notifications/{n['id']}/read", {}, headers).status_code, 200
        )
        self.assertTrue(
            self.client.get("/api/notifications", headers=headers).json()[0]["seen"]
        )

    def test_emergency_sms_stays_mock(self):
        headers, user = self.new_patient()
        self.post("/symptoms", {"symptoms": "chest pain"}, headers)
        outbox = self.client.get("/api/integrations/outbox", headers=headers).json()
        self.assertEqual(outbox[0]["status"], "mock")
        self.assertIn("no message sent", outbox[0]["payload"])

    def test_integration_status_no_credentials_exposed(self):
        r = self.client.get("/api/integrations", headers=self.patient)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()), 10)
        self.assertNotIn("JWT_SECRET", r.text)

    def test_health_history_and_export(self):
        headers, user = self.new_patient()
        self.post("/reports", {"text": "TSH: 2.1 mIU/L"}, headers)
        self.assertEqual(
            len(self.client.get("/api/records", headers=headers).json()), 1
        )
        data = self.client.get("/api/me/export", headers=headers).json()
        self.assertIn("notifications", data)
        self.assertNotIn("password", data["profile"])
        self.assertNotIn("session_key", data["profile"])

    def test_delete_cascades_and_old_token_stays_invalid(self):
        headers, user = self.new_patient()
        self.post("/symptoms", {"symptoms": "cough"}, headers)
        self.client.delete("/api/me", headers=headers)
        with db() as c:
            for table in [
                "records",
                "cases",
                "appointments",
                "notifications",
                "integration_outbox",
                "ingestion_keys",
            ]:
                self.assertEqual(
                    c.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (user["id"],)
                    ).fetchone()[0],
                    0,
                )
        # Insert a new user to exercise row-id reuse after deleting the last user.
        self.new_patient()
        self.assertEqual(self.client.get("/api/me", headers=headers).status_code, 401)

    def test_admin_can_access_review_queue(self):
        self.assertEqual(
            self.client.get("/api/cases", headers=self.admin).status_code, 200
        )
        self.assertEqual(
            self.client.get("/api/audit", headers=self.admin).status_code, 200
        )

    def test_clinician_cannot_submit_patient_health_forms(self):
        self.assertEqual(
            self.post("/symptoms", {"symptoms": "cough"}, self.doctor).status_code, 403
        )

    def test_nlp_offline_field_extraction(self):
        with patch.dict("os.environ", {"OLLAMA_ENABLED": "0"}):
            r = self.post(
                "/integrations/intake",
                {"text": "I am 35 years old with a cough for 3 days"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["age"], 35)
        self.assertEqual(r.json()["duration"], "3 days")
        self.assertEqual(r.json()["mode"], "offline extraction")

    def test_nlp_emergency_bypasses_model_and_queues(self):
        headers, user = self.new_patient()
        with patch("backend.local_nlp.extract") as model:
            r = self.post("/integrations/intake", {"text": "chest pain"}, headers)
            model.assert_not_called()
        self.assertEqual(r.json()["emergency"]["urgency"], "EMERGENCY")
        self.assertEqual(len(self.client.get("/api/cases", headers=headers).json()), 1)

    def test_nlp_model_invalid_output_falls_back(self):
        from backend.local_nlp import extract

        with (
            patch.dict(
                "os.environ",
                {"OLLAMA_ENABLED": "1", "OLLAMA_URL": "http://127.0.0.1:11434"},
            ),
            patch(
                "backend.local_nlp.urlopen",
                return_value=io.BytesIO(b'{"response":"not-json"}'),
            ),
        ):
            self.assertIn("offline extraction", extract("cough for 2 days")["mode"])

    def test_nlp_model_schema_valid_output(self):
        from backend.local_nlp import extract

        response = json.dumps(
            {"response": json.dumps({"duration": "2 days", "age": 30, "severity": 5})}
        ).encode()
        with (
            patch.dict(
                "os.environ",
                {"OLLAMA_ENABLED": "1", "OLLAMA_URL": "http://127.0.0.1:11434"},
            ),
            patch("backend.local_nlp.urlopen", return_value=io.BytesIO(response)),
        ):
            result = extract("30 years old, cough for 2 days, severity 5")
        self.assertEqual(result["age"], 30)
        self.assertIn("local Ollama", result["mode"])

    def test_nlp_refuses_remote_endpoint(self):
        with patch.dict(
            "os.environ", {"OLLAMA_ENABLED": "1", "OLLAMA_URL": "https://example.com"}
        ):
            self.assertEqual(
                self.post(
                    "/integrations/intake", {"text": "cough for 2 days"}
                ).status_code,
                422,
            )

    def test_mqtt_bridge_schema_and_topic(self):
        from integrations.mqtt_bridge import forward

        data = {"hr": 72, "spo2": 98, "temperature": 36.7, "event_id": "mqtt-test"}
        with patch(
            "integrations.mqtt_bridge.urlopen",
            return_value=io.BytesIO(b'{"accepted":true}'),
        ) as request:
            self.assertTrue(
                forward(
                    "mediassist/device/vitals",
                    json.dumps(data),
                    "fake-token",
                    "http://127.0.0.1:8000",
                    "device",
                )["accepted"]
            )
            sent = request.call_args.args[0]
            self.assertEqual(json.loads(sent.data)["device_id"], "device")
            self.assertEqual(sent.headers["Authorization"], "Bearer fake-token")
        with self.assertRaises(ValueError):
            forward(
                "unexpected/topic",
                json.dumps(data),
                "fake",
                "http://127.0.0.1:8000",
                "device",
            )

    def test_ocr_subprocess_adapter(self):
        from types import SimpleNamespace

        from backend.integrations import extract_image_text

        with (
            patch("backend.integrations.tesseract_path", return_value="tesseract"),
            patch(
                "backend.integrations.subprocess.run",
                return_value=SimpleNamespace(stdout="Glucose: 90 mg/dL"),
            ) as command,
        ):
            text = extract_image_text(b"\x89PNG\r\n\x1a\n", "png")
            self.assertEqual(text, "Glucose: 90 mg/dL")
            self.assertEqual(command.call_args.kwargs["timeout"], 30)
            self.assertNotIn("shell", command.call_args.kwargs)

    def test_startup_keeps_existing_consent(self):
        headers, user = self.new_patient()
        self.client.put("/api/me/consent", headers=headers, json={"consent": False})
        init()
        self.assertFalse(self.client.get("/api/me", headers=headers).json()["consent"])

    def test_concurrent_booking_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor

        headers, user = self.new_patient()
        payload = {"doctor_id": 6, "slot": self.future(days=8, time="12:00")}
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: self.post("/appointments", payload, headers).status_code,
                    range(2),
                )
            )
        self.assertEqual(sorted(results), [200, 409])

    def test_erasure_removes_linked_clinician_notes_from_audit(self):
        headers, user = self.new_patient()
        self.post("/symptoms", {"symptoms": "cough"}, headers)
        case = self.client.get("/api/cases", headers=headers).json()[0]
        note = "private-review-for-erasure-" + str(user["id"])
        self.post(
            f"/cases/{case['id']}/review",
            {"action": "approved", "note": note},
            self.doctor,
        )
        self.assertIn(note, self.client.get("/api/audit", headers=self.doctor).text)
        self.client.delete("/api/me", headers=headers)
        self.assertNotIn(note, self.client.get("/api/audit", headers=self.doctor).text)

    def test_legacy_database_migration_preserves_appointments_and_consent(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            file = str(Path(folder) / "legacy.db")
            con = sqlite3.connect(file)
            con.executescript("""
                CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT UNIQUE,name TEXT,role TEXT,password TEXT,consent INTEGER DEFAULT 0);
                CREATE TABLE doctors(id INTEGER PRIMARY KEY,name TEXT,specialty TEXT,city TEXT,language TEXT);
                CREATE TABLE appointments(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,doctor_id INTEGER REFERENCES doctors(id),slot TEXT,share INTEGER,UNIQUE(doctor_id,slot));
                INSERT INTO users VALUES(1,'legacy@test.local','Legacy Patient','patient','fake-test-hash',0);
                INSERT INTO doctors VALUES(1,'Legacy Doctor','General physician','Mumbai','English');
                INSERT INTO appointments VALUES(1,1,1,'2030-01-01T10:00',1);
            """)
            con.close()
            from backend.persistence import raw_connection

            init(file)
            with raw_connection(file) as c:
                self.assertEqual(
                    c.execute("SELECT consent FROM users WHERE id=1").fetchone()[0], 0
                )
                self.assertEqual(
                    c.execute("SELECT status FROM appointments WHERE id=1").fetchone()[
                        0
                    ],
                    "booked",
                )
                c.execute("UPDATE appointments SET status='cancelled' WHERE id=1")
                c.execute(
                    "INSERT INTO appointments(user_id,doctor_id,slot,share) VALUES(1,1,'2030-01-01T10:00',0)"
                )
                self.assertEqual(
                    c.execute("SELECT COUNT(*) FROM appointments").fetchone()[0], 2
                )


if __name__ == "__main__":
    unittest.main()

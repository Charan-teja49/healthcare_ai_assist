import secrets
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.lab_parser import parse
from backend.main import app


class ExtendedReportTests(unittest.TestCase):
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
                "email": secrets.token_hex(6) + "@report.test",
                "name": "Report Fixture",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_printed_range_overrides_example_without_conversion(self):
        row = parse("Glucose: 5.2 mmol/L reference range: 3.9 - 5.5")[0]
        self.assertEqual(row["value"], 5.2)
        self.assertEqual(row["reference_source"], "printed report")
        self.assertEqual(row["flag"], "within supplied range")

    def test_value_representation_and_extended_panels(self):
        rows = parse(
            "Hemoglobin: 11.20 g/dL\nPlatelets: 180 10^3/uL\nCreatinine: 1.1 mg/dL\nSodium: 140 mmol/L\nVitamin B12: 250 pg/mL"
        )
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["display_value"], "11.20")

    def test_unknown_units_not_converted(self):
        self.assertEqual(
            parse("Cholesterol: 4.9 mmol/L")[0]["flag"], "unit needs review"
        )

    def test_original_file_owner_and_doctor_scope(self):
        h = self.patient()
        other = self.patient()
        content = b"TSH: 2.1 mIU/L"
        r = self.client.post(
            "/api/reports/upload", headers=h, files={"file": ("original.txt", content)}
        )
        self.assertEqual(r.status_code, 200, r.text)
        identity = r.json()["document_id"]
        self.assertEqual(
            self.client.get(
                "/api/reports/documents/" + str(identity), headers=h
            ).content,
            content,
        )
        self.assertEqual(
            self.client.get(
                "/api/reports/documents/" + str(identity), headers=other
            ).status_code,
            403,
        )
        d = self.client.post(
            "/api/auth/login",
            json={"email": "doctor@demo.local", "password": "Demo@12345"},
        ).json()
        doctor = {"Authorization": "Bearer " + d["token"]}
        self.assertEqual(
            self.client.get(
                "/api/reports/documents/" + str(identity), headers=doctor
            ).status_code,
            200,
        )
        self.client.put("/api/me/consent", headers=h, json={"consent": False})
        self.assertEqual(
            self.client.get(
                "/api/reports/documents/" + str(identity), headers=doctor
            ).status_code,
            403,
        )

    def test_missing_ocr_setup_for_scanned_pdf(self):
        import io

        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        data = io.BytesIO()
        writer.write(data)
        with patch("backend.integrations.tesseract_path", return_value=None):
            r = self.client.post(
                "/api/reports/upload",
                headers=self.patient(),
                files={"file": ("scan.pdf", data.getvalue())},
            )
        self.assertEqual(r.status_code, 503)

    def test_invalid_printed_reference_preserved_without_nonfinite_json(self):
        import json

        row = parse("Glucose: 108 bananas range 120-70")[0]
        self.assertEqual(row["reference_low"], 120)
        self.assertEqual(row["reference_high"], 70)
        self.assertIn("bananas", row["reference"])
        huge = parse("Glucose: 108 mg/dL range 1e999-200")[0]
        self.assertEqual(huge["reference_low"], None)
        json.dumps(huge, allow_nan=False)

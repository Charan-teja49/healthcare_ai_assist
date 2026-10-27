import secrets
import time
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend import test_api as fixtures  # noqa: F401 - creates isolated test DB before app import
from backend.main import app


class DeviceTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def patient(self):
        result = self.client.post(
            "/api/auth/register",
            json={
                "email": secrets.token_hex(6) + "@device.test",
                "name": "Device Fixture",
                "password": "LongPassword123",
                "consent": True,
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["token"]

    def packet(self, **changes):
        return {
            "kind": "vitals",
            "device_id": "fixture",
            "event_id": secrets.token_hex(8),
            "timestamp": time.time(),
            "hr": 72,
            "spo2": 98,
            "temperature": 36.7,
            **changes,
        }

    def post(self, token, packet):
        return self.client.post(
            "/api/devices/ingest",
            headers={"Authorization": "Bearer " + token},
            json=packet,
        )

    def test_http_shared_schema_and_dedup(self):
        token = self.patient()
        packet = self.packet()
        self.assertEqual(self.post(token, packet).status_code, 200)
        self.assertTrue(self.post(token, packet).json()["duplicate"])
        self.assertEqual(
            self.post(token, {**packet, "event_id": "bad", "spo2": 105}).status_code,
            422,
        )

    def test_ecg_resampling_persisted(self):
        import numpy as np

        token = self.patient()
        packet = self.packet(
            kind="ecg",
            sample_rate=360,
            samples=np.sin(np.arange(360) * 2 * np.pi * 5 / 360).tolist(),
        )
        for key in ["hr", "spo2", "temperature"]:
            packet.pop(key)
        result = self.post(token, packet)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()["samples"]), 250)
        self.assertEqual(result.json()["source_sample_rate"], 360)
        self.assertTrue(self.post(token, packet).json()["duplicate"])

    def test_websocket_authenticated_fanout(self):
        token = self.patient()
        with (
            self.client.websocket_connect("/ws/vitals") as one,
            self.client.websocket_connect("/ws/vitals") as two,
        ):
            one.send_json({"token": token})
            two.send_json({"token": token})
            self.assertEqual(one.receive_json()["type"], "ready")
            self.assertEqual(two.receive_json()["type"], "ready")
            packet = self.packet()
            self.assertEqual(self.post(token, packet).status_code, 200)
            for connection in [one, two]:
                result = connection.receive_json()
                while result.get("type") == "heartbeat":
                    result = connection.receive_json()
                self.assertEqual(result["event_id"], packet["event_id"])

    def test_websocket_invalid_token(self):
        with self.client.websocket_connect("/ws/vitals") as ws:
            ws.send_json({"token": "invalid"})
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()

    def test_latest_is_patient_scoped(self):
        one = self.patient()
        two = self.patient()
        self.post(one, self.packet())
        result = self.client.get(
            "/api/devices/latest", headers={"Authorization": "Bearer " + two}
        )
        self.assertEqual(result.json()["kind"], "empty")

    def test_twenty_four_hour_buckets(self):
        token = self.patient()
        self.post(token, self.packet())
        response = self.client.get(
            "/api/devices/trends", headers={"Authorization": "Bearer " + token}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["buckets"]), 24)
        self.assertEqual(sum(b["count"] for b in response.json()["buckets"]), 1)
        self.assertEqual(
            self.client.get(
                "/api/devices/trends?hours=25",
                headers={"Authorization": "Bearer " + token},
            ).status_code,
            422,
        )

    def test_device_consent_gate(self):
        token = self.patient()
        self.client.put(
            "/api/me/consent",
            headers={"Authorization": "Bearer " + token},
            json={"consent": False},
        )
        self.assertEqual(self.post(token, self.packet()).status_code, 403)

    def test_disconnected_canonical_packet_no_vitals(self):
        token = self.patient()
        packet = {
            "kind": "event",
            "event": "leads_off",
            "device_id": "fixture",
            "event_id": "leads",
            "timestamp": time.time(),
        }
        result = self.post(token, packet)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()["signal"])
        self.assertEqual(
            self.client.get(
                "/api/vitals", headers={"Authorization": "Bearer " + token}
            ).json(),
            [],
        )

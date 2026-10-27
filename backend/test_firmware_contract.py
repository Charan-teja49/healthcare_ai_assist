"""Firmware contract fixtures verify formats; hardware timing needs a connected board."""

import json
import time
import unittest
from pathlib import Path

from backend.ingestion import SensorPacket

ROOT = Path(__file__).resolve().parents[1]


class FirmwareContractTests(unittest.TestCase):
    def test_pinout_and_sampling_target(self):
        pins = (ROOT / "firmware/include/pins.h").read_text()
        for name, value in {
            "I2C_SDA": 21,
            "I2C_SCL": 22,
            "ECG_ADC": 34,
            "TEMPERATURE_PIN": 4,
            "BUZZER_PIN": 27,
            "ECG_HZ": 250,
            "ECG_FRAME_SAMPLES": 250,
        }.items():
            self.assertRegex(pins, rf"{name}\s*=\s*{value}\s*;")

    def test_firmware_json_examples_match_shared_schema(self):
        common = {
            "device_id": "esp32-demo",
            "event_id": "boot-1",
            "timestamp": time.time(),
            "source": "device",
            "activity": "unknown",
            "acceleration_mode": "raw",
        }
        packets = [
            {
                **common,
                "kind": "vitals",
                "hr": 72.0,
                "spo2": 98.0,
                "temperature": 36.7,
                "acceleration": {"magnitude": 1.0},
            },
            {**common, "kind": "ecg", "sample_rate": 250, "samples": [0.0] * 250},
            {
                **common,
                "kind": "event",
                "event": "fall",
                "acceleration": {"magnitude": 3.6},
            },
            {**common, "kind": "event", "event": "leads_off", "signal": False},
            {**common, "kind": "event", "event": "restored", "signal": True},
        ]
        for payload in packets:
            self.assertEqual(
                SensorPacket.model_validate_json(json.dumps(payload)).kind,
                payload["kind"],
            )

    def test_source_suppresses_missing_readings_and_tags_simulation(self):
        source = (ROOT / "firmware/src/main.cpp").read_text()
        self.assertIn("if(pulseValid&&temperatureValid)", source)
        self.assertIn("if(leadsOff()||!clockReady())", source)
        self.assertIn('MEDIASSIST_SIMULATOR?"simulator":"device"', source)
        self.assertIn("vTaskDelayUntil", source)
        self.assertIn("xQueueCreate(2,sizeof(ECGFrame))", source)

    def test_both_compilation_profiles_are_explicit(self):
        source = (ROOT / "firmware/platformio.ini").read_text()
        self.assertIn("[env:esp32-sim]", source)
        self.assertIn("[env:esp32-sensors]", source)
        self.assertIn("MEDIASSIST_SIMULATOR=1", source)
        self.assertIn("MEDIASSIST_SIMULATOR=0", source)

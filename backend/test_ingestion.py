"""Isolated shared-schema and signal tests; never imports backend.main."""

import math
import time
import unittest
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError

from backend.ingestion import (
    MAX_ECG_SAMPLES,
    SCENARIOS,
    SensorPacket,
    resample_ecg,
    simulate_packet,
    synthetic_ecg,
)


class SensorPacketTests(unittest.TestCase):
    def base(self, **changes):
        return {
            "kind": "vitals",
            "device_id": "device-1",
            "event_id": "event-1",
            "timestamp": time.time(),
            "hr": 72.0,
            "spo2": 98.0,
            "temperature": 36.7,
            **changes,
        }

    def ecg(self, **changes):
        return {
            "kind": "ecg",
            "device_id": "device-1",
            "event_id": "ecg-1",
            "timestamp": time.time(),
            "sample_rate": 360,
            "samples": [0.1] * 360,
            **changes,
        }

    def test_valid_vitals_and_wire_roundtrip(self):
        packet = SensorPacket.model_validate(self.base(activity="walking"))
        self.assertEqual(packet.kind, "vitals")
        self.assertEqual(packet.activity, "walking")
        self.assertEqual(
            SensorPacket.model_validate_json(packet.model_dump_json()), packet
        )

    def test_all_required_packet_fields(self):
        valid = self.base()
        for field in ("kind", "device_id", "event_id", "timestamp"):
            with self.subTest(field=field):
                body = dict(valid)
                body.pop(field)
                with self.assertRaises(ValidationError):
                    SensorPacket.model_validate(body)

    def test_missing_vitals_fields(self):
        for field in ("hr", "spo2", "temperature"):
            with self.subTest(field=field):
                body = self.base()
                body.pop(field)
                with self.assertRaises(ValidationError):
                    SensorPacket.model_validate(body)

    def test_ids_trim_and_bounds(self):
        self.assertEqual(
            SensorPacket.model_validate(self.base(device_id=" device ")).device_id,
            "device",
        )
        for field in ("device_id", "event_id"):
            for value in ("", "   ", "x" * 101):
                with self.subTest(field=field, size=len(value)):
                    with self.assertRaises(ValidationError):
                        SensorPacket.model_validate(self.base(**{field: value}))

    def test_timestamp_bounds_and_nonfinite(self):
        with patch("backend.ingestion.time.time", return_value=1000.0):
            self.assertEqual(
                SensorPacket.model_validate(self.base(timestamp=1060)).timestamp,
                1060,
            )
            for value in (0, -1, 1060.01, float("nan"), float("inf"), True):
                with self.subTest(timestamp=value):
                    with self.assertRaises(ValidationError):
                        SensorPacket.model_validate(self.base(timestamp=value))

    def test_vital_bounds_and_nonfinite(self):
        for field, values in {
            "hr": (24.99, 250.01, float("nan")),
            "spo2": (49.99, 100.01, float("inf")),
            "temperature": (29.99, 45.01, -float("inf")),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        SensorPacket.model_validate(self.base(**{field: value}))
        for fields in (
            {"hr": 25, "spo2": 50, "temperature": 30},
            {"hr": 250, "spo2": 100, "temperature": 45},
        ):
            SensorPacket.model_validate(self.base(**fields))

    def test_unknown_fields_and_activity_rejected(self):
        for body in (
            self.base(activity="swimming"),
            self.base(extra="unexpected"),
            self.base(kind="unknown"),
            self.base(source="cloud"),
        ):
            with self.subTest(body=body):
                with self.assertRaises(ValidationError):
                    SensorPacket.model_validate(body)

    def test_ecg_requires_samples_and_rate(self):
        for field in ("samples", "sample_rate"):
            body = self.ecg()
            body.pop(field)
            with self.assertRaises(ValidationError):
                SensorPacket.model_validate(body)

    def test_ecg_sample_lengths(self):
        for size in (24, MAX_ECG_SAMPLES + 1):
            with self.assertRaises(ValidationError):
                SensorPacket.model_validate(self.ecg(samples=[0.0] * size))
        for size in (25, MAX_ECG_SAMPLES):
            self.assertEqual(
                len(
                    SensorPacket.model_validate(self.ecg(samples=[0.0] * size)).samples
                ),
                size,
            )

    def test_ecg_nonfinite_and_non_numeric_samples(self):
        for value in (float("nan"), float("inf"), -float("inf"), "bad", True):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    SensorPacket.model_validate(self.ecg(samples=[0.0] * 25 + [value]))

    def test_ecg_sample_rates(self):
        for rate in (249, 251, 0, True, "360", 360.0):
            with self.subTest(rate=rate):
                with self.assertRaises(ValidationError):
                    SensorPacket.model_validate(self.ecg(sample_rate=rate))
        for rate in (250, 360):
            self.assertEqual(
                SensorPacket.model_validate(self.ecg(sample_rate=rate)).sample_rate,
                rate,
            )

    def test_cross_kind_fields_rejected(self):
        for body in (
            self.base(event="fall"),
            self.base(sample_rate=250, samples=[0.0] * 250),
            self.ecg(hr=72),
            {
                "kind": "event",
                "device_id": "device",
                "event_id": "event",
                "timestamp": time.time(),
                "event": "fall",
                "hr": 72,
            },
        ):
            with self.assertRaises(ValidationError):
                SensorPacket.model_validate(body)

    def test_event_names_and_missing_event(self):
        base = {
            "kind": "event",
            "device_id": "device",
            "event_id": "event",
            "timestamp": time.time(),
        }
        for event in ("fall", "leads_off", "restored"):
            self.assertEqual(
                SensorPacket.model_validate({**base, "event": event}).event, event
            )
        for body in (base, {**base, "event": "unknown"}):
            with self.assertRaises(ValidationError):
                SensorPacket.model_validate(body)

    def test_disconnected_sensor_never_carries_measurements(self):
        packet = SensorPacket.model_validate(
            {
                "kind": "event",
                "device_id": "device",
                "event_id": "event",
                "timestamp": time.time(),
                "event": "leads_off",
            }
        )
        self.assertFalse(packet.signal)
        self.assertNotIn("hr", packet.model_dump(exclude_none=True))
        for body in (self.base(signal=False), self.ecg(signal=False)):
            with self.assertRaises(ValidationError):
                SensorPacket.model_validate(body)

    def test_acceleration_representations(self):
        xyz = SensorPacket.model_validate(
            self.base(acceleration={"x": 3.0, "y": 4.0, "z": 0.0})
        )
        self.assertEqual(xyz.acceleration_magnitude(), 5.0)
        for value in (3.6, {"magnitude": 3.6}):
            self.assertEqual(
                SensorPacket.model_validate(
                    self.base(acceleration=value)
                ).acceleration_magnitude(),
                3.6,
            )

    def test_acceleration_bounds_and_invalid_shapes(self):
        for value in (
            -0.1,
            32.1,
            float("nan"),
            float("inf"),
            True,
            {"magnitude": -1},
            {"x": 1, "y": 0},
            {"x": 0, "y": 0, "z": 0, "magnitude": 0},
            {"x": 32, "y": 32, "z": 32},
            {"x": float("nan"), "y": 0, "z": 0},
        ):
            with self.subTest(acceleration=value):
                with self.assertRaises(ValidationError):
                    SensorPacket.model_validate(self.base(acceleration=value))


class ECGSignalTests(unittest.TestCase):
    def test_equal_rate_copies_input(self):
        original = [0.1] * 250
        result = resample_ecg(original, 250)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_duration_preserved_both_directions(self):
        for source, target, length in (
            (360, 250, 1080),
            (250, 360, 750),
            (360, 250, 359),
        ):
            with self.subTest(source=source, target=target, length=length):
                values = np.sin(2 * np.pi * 5 * np.arange(length) / source)
                result = resample_ecg(values, source, target)
                self.assertEqual(len(result), math.ceil(length * target / source))
                self.assertLessEqual(
                    abs(len(result) / target - length / source), 1 / target
                )

    def test_sine_frequency_and_amplitude_preserved(self):
        source, target, seconds, frequency = 360, 250, 3, 7
        original = np.sin(2 * np.pi * frequency * np.arange(source * seconds) / source)
        result = np.array(resample_ecg(original, source, target))
        ideal = np.sin(2 * np.pi * frequency * np.arange(len(result)) / target)
        self.assertGreater(np.corrcoef(result[15:-15], ideal[15:-15])[0, 1], 0.999)
        self.assertLess(np.sqrt(np.mean((result[15:-15] - ideal[15:-15]) ** 2)), 0.01)
        frequencies = np.fft.rfftfreq(len(result), 1 / target)
        measured = frequencies[np.argmax(np.abs(np.fft.rfft(result)))]
        self.assertAlmostEqual(measured, frequency, places=6)

    def test_downsampling_attenuates_out_of_band_signal(self):
        # A 150 Hz tone is above the new 125 Hz Nyquist limit.
        original = np.sin(2 * np.pi * 150 * np.arange(1080) / 360)
        result = np.array(resample_ecg(original, 360, 250))
        self.assertLess(np.sqrt(np.mean(result[30:-30] ** 2)), 0.02)

    def test_resampling_rejects_invalid_input(self):
        for samples, source, target in (
            ([0.0] * 24, 360, 250),
            ([0.0] * 7201, 360, 250),
            ([float("nan")] * 25, 360, 250),
            ([0.0] * 25, 249, 250),
            ([0.0] * 25, 360.0, 250),
            ([0.0] * 25, 360, 100),
            ([True] * 25, 360, 250),
            ([[0.0]] * 25, 360, 250),
        ):
            with self.subTest(source=source, target=target):
                with self.assertRaises(ValueError):
                    resample_ecg(samples, source, target)

    def test_synthetic_waveform_is_repeatable_and_finite(self):
        for rate in (250, 360):
            first = synthetic_ecg(index=5, sample_rate=rate)
            self.assertEqual(first, synthetic_ecg(index=5, sample_rate=rate))
            self.assertEqual(len(first), rate)
            self.assertTrue(np.isfinite(first).all())
            self.assertGreater(max(first), 0.8)
            self.assertLess(min(first), -0.1)

    def test_synthetic_waveform_continuity(self):
        full = synthetic_ecg(index=0, duration_seconds=2)
        parts = synthetic_ecg(index=0) + synthetic_ecg(index=1)
        self.assertTrue(np.allclose(full, parts))

    def test_synthetic_waveform_rejects_invalid_parameters(self):
        for options in (
            {"sample_rate": 100},
            {"index": -1},
            {"duration_seconds": 0},
            {"duration_seconds": 100},
            {"heart_rate": float("nan")},
            {"heart_rate": 251},
            {"duration_seconds": "1"},
            {"heart_rate": None},
        ):
            with self.assertRaises(ValueError):
                synthetic_ecg(**options)


class SimulatorTests(unittest.TestCase):
    def test_all_six_scenarios_are_valid(self):
        for scenario in SCENARIOS:
            for index in (0, 1, 10):
                with self.subTest(scenario=scenario, index=index):
                    packet = simulate_packet(scenario, index, timestamp=1000.0)
                    self.assertEqual(packet.source, "simulator")
                    self.assertEqual(
                        SensorPacket.model_validate(packet.model_dump()), packet
                    )

    def test_packet_is_deterministic_with_explicit_timestamp(self):
        self.assertEqual(
            simulate_packet("normal_rest", 4, timestamp=1000),
            simulate_packet("normal_rest", 4, timestamp=1000),
        )
        self.assertNotEqual(
            simulate_packet("normal_rest", 4, timestamp=1000).event_id,
            simulate_packet("normal_rest", 5, timestamp=1000).event_id,
        )

    def test_disconnected_scenario_is_an_event_not_a_reading(self):
        packet = simulate_packet("leads_off", 0, timestamp=1000)
        self.assertEqual(packet.kind, "event")
        self.assertEqual(packet.event, "leads_off")
        self.assertFalse(packet.signal)
        self.assertIsNone(packet.hr)
        self.assertIsNone(packet.samples)

    def test_scenario_values_represent_expected_educational_conditions(self):
        self.assertGreater(simulate_packet("arrhythmia_episode", 0).hr, 120)
        self.assertLess(simulate_packet("low_spo2", 0).spo2, 92)
        self.assertGreater(simulate_packet("fever", 0).temperature, 38.5)
        impact = simulate_packet("fall", 0)
        still = simulate_packet("fall", 1)
        self.assertEqual(impact.event, "fall")
        self.assertGreater(impact.acceleration_magnitude(), 3)
        self.assertLess(still.acceleration_magnitude(), 0.1)

    def test_unknown_scenario_and_bad_index_rejected(self):
        for scenario, index in (
            ("unknown", 0),
            ("normal_rest", -1),
            ("normal_rest", True),
        ):
            with self.assertRaises(ValueError):
                simulate_packet(scenario, index)


if __name__ == "__main__":
    unittest.main()

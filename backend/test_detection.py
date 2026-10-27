import tempfile
import unittest

import numpy as np

from backend.detection import (
    IsolationForest,
    baseline,
    fall_detect,
    hrv,
    r_peaks,
    sustained_rules,
)
from backend.ecg_model import BeatCNN, synthetic_dataset, train_and_evaluate
from backend.ingestion import synthetic_ecg


class DetectionTests(unittest.TestCase):
    def row(self, t, **changes):
        return {
            "hr": 72,
            "spo2": 98,
            "temperature": 36.7,
            "timestamp": t,
            "activity": "rest",
            **changes,
        }

    def test_single_spike_not_sustained(self):
        self.assertEqual(
            sustained_rules([], self.row(10, hr=140))["sustained_flags"], []
        )

    def test_ten_second_window(self):
        rows = [self.row(t, spo2=88) for t in range(11)]
        self.assertIn(
            "low_spo2", sustained_rules(rows[:-1], rows[-1])["sustained_flags"]
        )

    def test_gap_resets_window(self):
        rows = [self.row(1, spo2=88), self.row(12, spo2=88)]
        self.assertEqual(sustained_rules(rows[:-1], rows[-1])["sustained_flags"], [])

    def test_activity_does_not_suppress_low_oxygen(self):
        row = self.row(10, hr=150, spo2=88, activity="running")
        self.assertNotIn("high_hr", sustained_rules([], row)["instant_flags"])
        self.assertIn("low_spo2", sustained_rules([], row)["instant_flags"])

    def test_isolation_outlier_score(self):
        r = np.random.default_rng(1)
        data = r.normal(0, 1, (100, 3))
        model = IsolationForest().fit(data)
        self.assertGreater(model.score([15, 15, 15]), model.score([0, 0, 0]))
        self.assertAlmostEqual(
            model.score([0, 0, 0]), IsolationForest().fit(data).score([0, 0, 0])
        )

    def test_baseline_needs_ten_samples(self):
        self.assertFalse(baseline([self.row(1)] * 9, self.row(2))["ready"])
        self.assertTrue(baseline([self.row(1)] * 10, self.row(2, hr=110))["deviation"])

    def test_hrv_known_intervals(self):
        result = hrv([0, 250, 525], 250)
        self.assertAlmostEqual(result["sdnn_ms"], 70.710678, places=4)
        self.assertAlmostEqual(result["rmssd_ms"], 100)

    def test_synthetic_peak_detection(self):
        samples = synthetic_ecg(duration_seconds=8, heart_rate=72)
        peaks = r_peaks(samples, 250)
        self.assertGreaterEqual(len(peaks), 8)
        self.assertLessEqual(len(peaks), 11)
        self.assertAlmostEqual(hrv(peaks, 250)["heart_rate"], 72, delta=3)

    def test_flat_ecg_no_peaks(self):
        self.assertEqual(r_peaks([0] * 500, 250), [])

    def test_impact_then_stillness(self):
        rows = [{"timestamp": 0, "acceleration": 3.6}] + [
            {"timestamp": i, "acceleration": 0.05} for i in range(1, 4)
        ]
        self.assertTrue(fall_detect(rows))
        self.assertFalse(fall_detect(rows[:2]))
        self.assertFalse(
            fall_detect([{"timestamp": i, "acceleration": 3.6} for i in range(4)])
        )

    def test_raw_gravity_stillness(self):
        rows = [{"timestamp": 0, "acceleration": 3.6, "acceleration_mode": "raw"}] + [
            {"timestamp": i, "acceleration": 1.0, "acceleration_mode": "raw"}
            for i in range(1, 4)
        ]
        self.assertTrue(fall_detect(rows))

    def test_cnn_training_and_safe_artifact(self):
        x, y, groups = synthetic_dataset()
        model = BeatCNN().fit(x[groups < 6], y[groups < 6], epochs=15)
        self.assertGreater(
            float(
                np.mean(model.predict_proba(x[groups >= 8]).argmax(1) == y[groups >= 8])
            ),
            0.6,
        )
        with tempfile.TemporaryDirectory() as folder:
            from pathlib import Path

            file = Path(folder) / "model.npz"
            model.save(file)
            loaded = BeatCNN.load(file)
            np.testing.assert_allclose(
                model.predict_proba(x[:3]), loaded.predict_proba(x[:3])
            )

    def test_model_evaluation_group_split(self):
        with tempfile.TemporaryDirectory() as folder:
            result = train_and_evaluate(folder)
            self.assertFalse(result["clinical_validation"])
            self.assertEqual(
                sum(map(sum, result["confusion_matrix"])), result["test_samples"]
            )
            self.assertTrue(
                set(result["train_patient_groups"]).isdisjoint(
                    result["test_patient_groups"]
                )
            )

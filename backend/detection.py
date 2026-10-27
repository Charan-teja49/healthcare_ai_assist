"""Educational detection algorithms; not validated clinical alarm thresholds."""

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RuleConfig:
    sustain_seconds: float = 10
    max_gap_seconds: float = 5
    rest_hr_high: float = 120
    active_hr_high: float = 180
    hr_low: float = 45
    spo2_low: float = 92
    temperature_high: float = 38.5


def sustained_rules(history, current, config=None):
    config = config or RuleConfig()
    rows = sorted(
        [
            *[r for r in history if r.get("timestamp", 0) < current["timestamp"]],
            current,
        ],
        key=lambda r: r.get("timestamp", 0),
    )

    def flags(row):
        active = row.get("activity") in ("walking", "running")
        return {
            "high_hr": row["hr"]
            > (config.active_hr_high if active else config.rest_hr_high),
            "low_hr": row["hr"] < config.hr_low,
            "low_spo2": row["spo2"] < config.spo2_low,
            "fever": row["temperature"] >= config.temperature_high,
        }

    instant = [k for k, v in flags(current).items() if v]
    sustained = []
    for flag in instant:
        end = current["timestamp"]
        start = end
        previous = end
        for row in reversed(rows[:-1]):
            stamp = row.get("timestamp", 0)
            if stamp > end:
                continue
            if previous - stamp > config.max_gap_seconds or not flags(row)[flag]:
                break
            start = stamp
            previous = stamp
        if end - start >= config.sustain_seconds:
            sustained.append(flag)
    return {
        "instant_flags": instant,
        "sustained_flags": sustained,
        "sustained_seconds_required": config.sustain_seconds,
    }


def _c(size):
    if size <= 1:
        return 0.0
    return 2 * sum(1 / i for i in range(1, size)) - 2 * (size - 1) / size


class IsolationForest:
    """Original random-partition/path-length method, NumPy-only and reproducible."""

    def __init__(self, trees=32, sample_size=64, seed=42):
        self.trees_count = trees
        self.sample_size = sample_size
        self.rng = np.random.default_rng(seed)
        self.trees = []

    def fit(self, data):
        data = np.asarray(data, dtype=float)
        if data.ndim != 2 or len(data) < 10 or not np.isfinite(data).all():
            raise ValueError("At least ten finite feature rows are required")
        self.n = min(len(data), self.sample_size)
        limit = math.ceil(math.log2(self.n))

        def build(x, depth):
            varying = np.flatnonzero(np.ptp(x, axis=0) > 1e-12)
            if len(x) <= 1 or depth >= limit or not len(varying):
                return len(x)
            feature = int(self.rng.choice(varying))
            split = float(self.rng.uniform(x[:, feature].min(), x[:, feature].max()))
            left = x[:, feature] < split
            if not left.any() or left.all():
                return len(x)
            return (
                feature,
                split,
                build(x[left], depth + 1),
                build(x[~left], depth + 1),
            )

        self.trees = [
            build(data[self.rng.choice(len(data), self.n, replace=False)], 0)
            for _ in range(self.trees_count)
        ]
        return self

    def score(self, row):
        if not self.trees:
            raise ValueError("Fit a baseline before scoring")
        row = np.asarray(row, dtype=float)
        if not np.isfinite(row).all():
            raise ValueError("Non-finite features")

        def path(node, depth=0):
            if isinstance(node, int):
                return depth + _c(node)
            f, s, left, right = node
            return path(left if row[f] < s else right, depth + 1)

        return float(2 ** (-np.mean([path(t) for t in self.trees]) / _c(self.n)))


def baseline(history, current):
    clean = [
        r
        for r in history
        if not r.get("alert")
        and 45 <= r["hr"] <= 120
        and r["spo2"] >= 92
        and r["temperature"] < 38.5
    ][-128:]
    if len(clean) < 10:
        return {
            "ready": False,
            "sample_count": len(clean),
            "score": None,
            "deviation": False,
        }
    data = np.array([[r[k] for k in ["hr", "spo2", "temperature"]] for r in clean])
    row = np.array([current[k] for k in ["hr", "spo2", "temperature"]])
    score = IsolationForest().fit(data).score(row)
    deviation = bool(
        np.any(abs(row - data.mean(0)) > np.maximum(data.std(0) * 3, [15, 4, 1]))
    )
    return {
        "ready": True,
        "sample_count": len(clean),
        "score": score,
        "deviation": deviation or score > 0.7,
    }


def r_peaks(samples, sample_rate):
    """Bandpass, derivative, squaring, moving integration and refractory search."""
    x = np.asarray(samples, dtype=float)
    if (
        x.ndim != 1
        or len(x) < sample_rate
        or sample_rate not in (250, 360)
        or not np.isfinite(x).all()
    ):
        return []
    spectrum = np.fft.rfft(x - x.mean())
    freq = np.fft.rfftfreq(len(x), 1 / sample_rate)
    spectrum[(freq < 5) | (freq > 18)] = 0
    filtered = np.fft.irfft(spectrum, n=len(x))
    derivative = np.gradient(filtered)
    width = max(1, int(0.15 * sample_rate))
    energy = np.convolve(derivative**2, np.ones(width) / width, "same")
    threshold = float(np.median(energy) + 0.3 * (energy.max() - np.median(energy)))
    candidates = (
        np.flatnonzero(
            (energy[1:-1] >= energy[:-2])
            & (energy[1:-1] > energy[2:])
            & (energy[1:-1] > threshold)
        )
        + 1
    )
    ordered = sorted(candidates, key=lambda p: energy[p], reverse=True)
    selected = []
    for point in ordered:
        left = max(0, point - int(0.15 * sample_rate))
        right = min(len(x), point + int(0.15 * sample_rate) + 1)
        peak = left + int(np.argmax(abs(x[left:right] - np.median(x))))
        if all(abs(peak - old) >= int(0.25 * sample_rate) for old in selected):
            selected.append(peak)
    return [int(value) for value in sorted(selected)]


def hrv(peaks, sample_rate):
    rr = np.diff(np.asarray(peaks, dtype=float)) / sample_rate * 1000
    if len(rr) < 1 or np.any(rr <= 0):
        return {"rr_ms": [], "sdnn_ms": None, "rmssd_ms": None, "heart_rate": None}
    return {
        "rr_ms": rr.tolist(),
        "sdnn_ms": float(np.std(rr, ddof=1)) if len(rr) > 1 else None,
        "rmssd_ms": float(np.sqrt(np.mean(np.diff(rr) ** 2))) if len(rr) > 1 else None,
        "heart_rate": float(60000 / rr.mean()),
    }


def fall_detect(rows, still_seconds=2):
    """Linear acceleration: >3g impact then <0.1g stillness; raw uses variance."""

    def magnitude(row):
        value = row.get("acceleration")
        if isinstance(value, dict):
            if value.get("magnitude") is not None:
                return value["magnitude"]
            return math.sqrt(sum(value.get(k, 0) ** 2 for k in ("x", "y", "z")))
        return value

    rows = sorted(
        [r for r in rows if magnitude(r) is not None], key=lambda r: r["timestamp"]
    )
    if len(rows) < 3:
        return False
    for i, row in enumerate(rows[:-2]):
        if magnitude(row) <= 3:
            continue
        quiet = rows[i + 1 :]
        if quiet[-1]["timestamp"] - quiet[0]["timestamp"] < still_seconds:
            continue
        if quiet[-1]["timestamp"] - row["timestamp"] > 10:
            continue
        if any(b["timestamp"] - a["timestamp"] > 2 for a, b in zip(quiet, quiet[1:])):
            continue
        values = np.array([magnitude(r) for r in quiet])
        raw = row.get("acceleration_mode") == "raw"
        if (
            (values.std() < 0.1 and abs(values.mean() - 1) < 0.2)
            if raw
            else bool(np.all(values < 0.1))
        ):
            return True
    return False

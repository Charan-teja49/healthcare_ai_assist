"""Research ECG measurements attached to the original signal, never a diagnosis."""

from functools import lru_cache
from pathlib import Path

import numpy as np

from backend.detection import hrv, r_peaks
from backend.ecg_model import CLASSES, BeatCNN


@lru_cache(maxsize=2)
def load_model(path, mtime):
    return BeatCNN.load(path)


def analyze(samples, sample_rate, source="device"):
    peaks = r_peaks(samples, sample_rate)
    result = {
        **hrv(peaks, sample_rate),
        "r_peaks": peaks,
        "sample_rate": sample_rate,
        "classification": [],
    }
    artifact = Path(__file__).parent.parent / "models/ecg-demo/ecg_cnn.npz"
    if not artifact.is_file() or source != "simulator":
        result["model_mode"] = (
            "No validated clinical classifier. Research synthetic model is only used on simulator data."
        )
        return result
    beats = [
        samples[p - 32 : p + 32] for p in peaks if p >= 32 and p + 32 <= len(samples)
    ]
    if beats:
        probabilities = load_model(
            str(artifact), artifact.stat().st_mtime
        ).predict_proba(np.asarray(beats))
        result["classification"] = [
            {"research_label": CLASSES[int(row.argmax())], "score": float(row.max())}
            for row in probabilities
        ]
    result["model_mode"] = (
        "Synthetic-trained demonstration model; not clinical accuracy or diagnostic guidance"
    )
    return result

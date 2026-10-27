"""Small trainable 1D CNN. Synthetic fallback metrics are not clinical accuracy."""

import json
from pathlib import Path

import numpy as np

CLASSES = ("N", "S", "V", "F", "Q")


class BeatCNN:
    def __init__(self, seed=42):
        r = np.random.default_rng(seed)
        self.w = r.normal(0, 0.3, (9, 6))
        self.b = np.zeros(6)
        self.v = r.normal(0, 0.06, (56 * 6, 5))
        self.c = np.zeros(5)

    def _features(self, x):
        x = np.asarray(x, dtype=float)
        x = (x - x.mean(1, keepdims=True)) / (x.std(1, keepdims=True) + 1e-6)
        windows = np.lib.stride_tricks.sliding_window_view(x, 9, axis=1)
        z = np.einsum("blk,kf->blf", windows, self.w) + self.b
        return windows, z, np.maximum(z, 0).reshape(len(x), -1)

    def predict_proba(self, x):
        _, _, features = self._features(x)
        logits = features @ self.v + self.c
        logits -= logits.max(1, keepdims=True)
        p = np.exp(logits)
        return p / p.sum(1, keepdims=True)

    def fit(self, x, y, epochs=40, learning_rate=0.025):
        r = np.random.default_rng(7)
        for _ in range(epochs):
            for ids in np.array_split(r.permutation(len(x)), max(1, len(x) // 64)):
                windows, z, feat = self._features(x[ids])
                logits = feat @ self.v + self.c
                logits -= logits.max(1, keepdims=True)
                p = np.exp(logits)
                p /= p.sum(1, keepdims=True)
                grad = p
                grad[np.arange(len(ids)), y[ids]] -= 1
                grad /= len(ids)
                dv = feat.T @ grad
                dc = grad.sum(0)
                dz = (grad @ self.v.T).reshape(z.shape) * (z > 0)
                dw = np.einsum("blf,blk->kf", dz, windows)
                db = dz.sum((0, 1))
                for param, g in [
                    (self.v, dv),
                    (self.c, dc),
                    (self.w, dw),
                    (self.b, db),
                ]:
                    param -= learning_rate * np.clip(g, -5, 5)
        return self

    def save(self, path):
        np.savez(path, w=self.w, b=self.b, v=self.v, c=self.c)

    @classmethod
    def load(cls, path):
        model = cls()
        data = np.load(path, allow_pickle=False)
        for k in ["w", "b", "v", "c"]:
            setattr(model, k, data[k])
        return model


def synthetic_dataset():
    rows = []
    labels = []
    patients = []
    t = np.linspace(-1, 1, 64)
    for patient in range(10):
        r = np.random.default_rng(100 + patient)
        for label in range(5):
            for _ in range(16):
                shift = r.normal(0, 0.025)
                u = t - shift
                shapes = [
                    np.exp(-((u / 0.065) ** 2))
                    - 0.25 * np.exp(-(((u - 0.12) / 0.08) ** 2)),
                    np.exp(-(((u + 0.12) / 0.045) ** 2))
                    + 0.4 * np.exp(-(((u - 0.08) / 0.04) ** 2)),
                    -np.exp(-((u / 0.25) ** 2))
                    + 0.2 * np.exp(-(((u - 0.4) / 0.1) ** 2)),
                    0.6 * np.exp(-(((u + 0.1) / 0.08) ** 2))
                    + 0.6 * np.exp(-(((u - 0.12) / 0.2) ** 2)),
                    r.normal(0, 0.4, 64),
                ]
                rows.append(shapes[label] + r.normal(0, 0.03, 64))
                labels.append(label)
                patients.append(patient)
    return np.array(rows), np.array(labels), np.array(patients)


def train_and_evaluate(output, dataset=None):
    """Optional NPZ: beats[n,64], labels[n] (0..4), patient_ids[n]. No pickle."""
    if dataset:
        loaded = np.load(dataset, allow_pickle=False)
        x = loaded["beats"]
        y = loaded["labels"]
        groups = loaded["patient_ids"]
        source = "user-supplied patient-grouped dataset"
    else:
        x, y, groups = synthetic_dataset()
        source = "synthetic fallback only"
    if (
        x.ndim != 2
        or x.shape[1] != 64
        or len(x) != len(y)
        or not np.isfinite(x).all()
        or not np.isin(y, range(5)).all()
    ):
        raise ValueError("Expected finite beats[n,64] and labels0..4")
    ids = np.unique(groups)
    if len(ids) < 5:
        raise ValueError("At least five independent patient groups are required")
    train_ids = ids[: int(0.6 * len(ids))]
    validation_ids = ids[int(0.6 * len(ids)) : int(0.8 * len(ids))]
    test_ids = ids[int(0.8 * len(ids)) :]
    train = np.isin(groups, train_ids)
    test = np.isin(groups, test_ids)
    model = BeatCNN().fit(x[train], y[train])
    predictions = model.predict_proba(x[test]).argmax(1)
    matrix = np.zeros((5, 5), dtype=int)
    for truth, pred in zip(y[test], predictions):
        matrix[int(truth), int(pred)] += 1
    metrics = {
        "dataset": source,
        "clinical_validation": False,
        "accuracy": float(np.mean(predictions == y[test])),
        "classes": list(CLASSES),
        "confusion_matrix": matrix.tolist(),
        "train_patient_groups": train_ids.tolist(),
        "validation_patient_groups": validation_ids.tolist(),
        "test_patient_groups": test_ids.tolist(),
        "test_samples": int(test.sum()),
        "architecture": "Conv1D(6 filters,9) -> ReLU -> flatten -> dense5 -> softmax",
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    model.save(output / "ecg_cnn.npz")
    (output / "evaluation.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    np.savetxt(output / "confusion_matrix.csv", matrix, fmt="%d", delimiter=",")
    return metrics


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="models/ecg-demo")
    parser.add_argument("--dataset")
    args = parser.parse_args()
    print(json.dumps(train_and_evaluate(args.output, args.dataset), indent=2))

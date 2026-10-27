# Personal baseline and Isolation Forest

Implementation: backend/detection.py. The latest 30 stored vitals provide a per-user baseline after at least 10 eligible readings. Obvious threshold breaches and readings already marked alert are excluded. Each sample contains HR, SpO2 and temperature; no cross-patient training occurs.

The NumPy Isolation Forest implements random partition trees and normalized path lengths (32 trees, up to 64 sampled rows, deterministic seed). An anomaly score above 0.7 or a deviation exceeding the larger of three standard deviations and fixed floors (15 bpm, 4 saturation points, 1°C) produces a research deviation alert. Absolute activity-aware thresholds require a sustained 10-second window with at most 5-second gaps; different devices do not contribute to each other's duration window.

These are educational defaults, not validated medical thresholds. Activity, sensor contact, fever and measurement error can affect the baseline and cause false alerts or missed events. No sensitivity/specificity, outcome or diagnostic accuracy is established. Clinicians inspect original measurements. Matching recent alerts coalesce by device and reason; different abnormal reasons can create separate cases.

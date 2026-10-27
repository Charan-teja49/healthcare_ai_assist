# Phase 3 local-software gate: passed
- Full backend suite: 125 passed plus124 subtests; two additional event-routing tests also passed.
- Timed thresholds distinguish single spikes from sustained10-second events and account for activity; personal rolling baseline and reproducible Isolation Forest scoring are separate signals.
- Impact-plus-stillness fall detection supports linear acceleration and gravity-aware raw magnitude fixtures.
- ECG processing implements a Pan-Tompkins-inspired bandpass/derivative/squared/integrated/refractory pipeline, RR intervals, sample SDNN and RMSSD. It is not a certified detector.
- A small end-to-end-trained NumPy Conv1D classifier is saved as a safe NPZ artifact. Reproducible patient-group split and confusion matrix are in models/ecg-demo/evaluation.json and confusion_matrix.csv.
- Observed held-out SYNTHETIC fixture accuracy:98.125% on160 generated beats. This is not MIT-BIH accuracy, clinical accuracy, or evidence of real arrhythmia detection. No real dataset/hardware is available.
- Synthetic-trained classification is only run on simulator-labelled packets. Physical device signals do not receive that unvalidated classification.
- Known HRV values, waveform peaks, outlier scoring, sustained-case routing and fall event generation all passed.
- Reference method: https://www.lamda.nju.edu.cn/publication/icdm08b.pdf . MIT-BIH evaluation and prospective clinical validation remain external gates.

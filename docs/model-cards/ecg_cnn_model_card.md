# ECG CNN: synthetic research demonstration

Artifact: models/ecg-demo/ecg_cnn.npz. Architecture: NumPy Conv1D with 6 filters of width 9, ReLU, flatten, dense 5-way softmax. Labels N/S/V/F/Q use AAMI-style categories for demonstration only.

The supplied evaluation is on generated 64-sample beat fixtures, with disjoint simulated patient groups: training 0–5, validation 6–7, held-out test 8–9. The held-out test contains 160 beats. Observed fixture accuracy is 0.98125 (98.125%); confusion matrix and split metadata are in models/ecg-demo/evaluation.json and confusion_matrix.csv. This measures discrimination of synthetic shapes. It provides no estimate of diagnostic accuracy, patient outcomes, or performance on real ECG.

MIT-BIH data was not supplied or used. The requested 96% clinical/real-dataset accuracy target is not demonstrated. Reserved validation groups are recorded but this compact training routine does not perform a hyperparameter search. No model selection claim is made.

Inference is restricted to packets explicitly tagged source=simulator. It does not determine urgency or prescribe treatment. Real device classification remains disabled pending external patient-disjoint evaluation, preprocessing review, calibration, clinician assessment and an appropriate validation dataset. Synthetic labels/scores must not be interpreted as disease probabilities.

Reproduce: python -m backend.ecg_model --output models/ecg-demo. An optional prepared NPZ may contain beats[n,64], labels[n] (0–4), and patient_ids[n]; use --dataset PATH. Preparing, licensing and reviewing a real dataset remains a separate task. Never commit patient datasets to this project.

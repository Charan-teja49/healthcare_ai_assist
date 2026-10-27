# MediAssist AI methodology

Use iterative prototyping with a doctor-in-the-loop design. Each phase has a working software gate in IMPLEMENTATION-LEDGER.md. Separate software correctness, model evaluation, language usability and clinical/hardware validation: success in one does not establish the others.

## Requirements and workflow

Translate the objective into patient, clinician and administrator workflows: authenticated symptom intake, report understanding, monitoring, timely preliminary guidance, specialist selection and review. Record health-processing and appointment-sharing consent separately. Use fictional data during development, define erasure/export behavior, and ensure emergency phrases never wait for a model or review queue.

## Architecture and implementation

Build React/Vite interfaces over FastAPI, SQLite and SQLAlchemy sync/async persistence. Add versioned non-destructive schema updates, fictional GP/cardiologist assignments, JWT revocation and role/owner checks. Implement a shared sensor packet contract for HTTP and MQTT, resampling, authenticated live streams, a safe offline PWA shell and reproducible scenarios.

Add activity-aware sustained rules and a personal baseline/Isolation Forest. Extract ECG peaks and HRV as research measurements. Train a small Conv1D demonstration on generated beat fixtures with disjoint simulated patient groups; store the artifact, confusion matrix, split metadata and model cards. Keep real-device classification disabled until clinical validation is available.

Implement conversational intake with structured follow-ups and deterministic fallback. Optional loopback adapters validate local-model field extraction and ranked hypotheses against strict schemas; model output cannot lower deterministic urgency and remains held for the assigned doctor. For reports, deterministic extraction preserves original numbers/units/source documents, uses clear printed ranges when valid, and flags ambiguity rather than inventing corrections.

Connect live review, original data, ECG context, edited approval, rejection, information requests and escalation. Patient replies preserve original submissions and requeue review. Background expiry gives conservative advice. Add approximate geospatial specialist filtering, protected sharing, serialized bookings and clinician availability controls.

Localize fixed UI and guided templates with i18next, retaining original clinical free text. Implement consented mock/provider notification adapters and a time-compressed six-scenario demo. Implement and compile both ESP32 profiles; retain physical sensor calibration and acquisition checks as separate hardware gates.

## Verification

Use isolated-database unit/integration tests for bounds, malformed data, persistence, duplicate/conflicting submissions, emergency bypass, role/assignment isolation, held and released outputs, follow-up replies, consent withdrawal, original-file protection, notification retries and erasure/export. Measure application coverage excluding test files and require at least 70%. Apply Ruff, JSX-aware ESLint, typed demo-contract checks and a frontend production build.

Use the connected browser to verify real login, six-scenario replay, guided questions, edited doctor approval, patient release, report values, language changes, filtering, bookings/cancellation, consent recovery, follow-up replies and export. Record measured timing and screenshots. A standalone Playwright test is included for repeatability; its execution status is stated separately.

## Future clinical and integration evaluation

Obtain appropriately licensed/de-identified ECG data, prepare patient-disjoint real train/validation/test splits and evaluate external datasets. Report per-class sensitivity/specificity, precision/recall/F1, confusion matrices and uncertainty. The synthetic score does not meet or establish a real-data 96% accuracy target.

Validate sensors against reference devices, inspect waveform quality and timing under network load, calibrate temperature/optical measurements, assess missing signals and validate body-safe hardware. Activate real OCR, broker, model and notification providers only with local configuration and their own accuracy/delivery checks. Verify real clinician directory entries before representing them as verified. Qualified clinical and linguistic review, production security/operations, and appropriate permissions are required before real patient deployment.

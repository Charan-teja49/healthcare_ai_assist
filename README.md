# MediAssist AI

A local healthcare-support prototype in your existing VS Code folder, using React/Vite, FastAPI, SQLite and SQLAlchemy. It supports guided symptoms, understandable reports, simulated sensor monitoring, assigned-clinician review and local appointment booking. Use fictional health data.

## Run in your existing folder

Open C:\\Users\\chara\\OneDrive\\Desktop\\MediAssist-AI-v0.2.1-Login-Fixed\\mediassist in VS Code. Keep using this folder for updates; no ZIP extraction is needed.

```powershell
powershell -ExecutionPolicy Bypass -File .\\start.ps1
```

Open http://127.0.0.1:5174 . API reference: http://127.0.0.1:8010/docs . Keep the terminal open; Ctrl+C stops the launched services. If these ports already serve this folder, use the running application. After a backend update, restart its terminal or launch with -Reload. Do not start a duplicate server on the same port.

Python 3.12+ and Node.js 22+ are required. First setup needs internet for dependencies. The current environment was tested with Python 3.14.5 and Node 24.15. Run commands and troubleshooting are in RUN-IN-VSCODE.md.

| Account | Email | Password |
|---|---|---|
| Patient | patient@demo.local | Demo@12345 |
| General physician | doctor@demo.local | Demo@12345 |
| Cardiologist | cardio@demo.local | Demo@12345 |
| Administrator | admin@demo.local | Demo@12345 |

Registration creates patient accounts. Seed accounts are fictional and pre-consented; startup preserves existing consent. Cardiologists receive vital alerts; the GP handles general symptoms, reports and fall review. Only the assigned doctor can approve a case. Administrators have oversight, not clinical approval authority.

## Implemented

- Authentication with Argon2, expiring JWT sessions, server-side logout revocation, bounded failed-login throttling and patient/doctor/admin access checks.
- Separate account health-processing consent and optional appointment sharing. Export, erasure, protected original report files and an integrity-linked audit trail.
- Persistent guided intake: symptoms, age, duration, severity, associated symptoms, conditions/medicines/allergies. Typed input and optional browser voice. Emergency phrases are checked before any local model call; ordinary condition suggestions remain held for doctor approval.
- Twenty-two deterministic lab labels covering CBC, lipids, metabolic, thyroid and vitamins. Printed ranges take precedence only when valid; unusual units or invalid ranges need review. Original numbers, units, source text and uploaded files are preserved. Text/PDF works locally; scanned PDF/image OCR needs optional local engines.
- Canonical HTTP/MQTT vitals, ECG and event schema, deduplication, 250/360Hz resampling, authenticated WebSockets, live Canvas ECG and 24-hour stored trends. Offline PWA fallback does not cache clinical records.
- Activity-aware sustained thresholds, per-user rolling baseline/Isolation Forest, R-peaks, RR/HRV and impact/stillness detection. A trainable CNN has a supplied held-out synthetic evaluation; real-device classification remains disabled.
- Live assigned-clinician queue; original data and ECG context; approve, edit and approve, reject, request information and escalate. Patients can answer information requests on the same case without changing the original submission. Background review expiry gives conservative fallback advice.
- Thirty fictional specialist profiles across six cities, combined distance/specialty/language/date filtering, half-hour IST availability, clinician block/reopen controls, booking/cancellation and consent-scoped shared records.
- i18next fixed English/Hindi interface and guided-question templates; Marathi/Tamil resource structure. User text, report originals and doctor notes stay in their original language. A bounded template-only cache cannot receive arbitrary health text.
- In-app notifications; local SMS mock by default; configured Twilio/Web Push adapters with consent checks, bounded definite-failure retries and ambiguous-delivery handling.
- Hidden http://127.0.0.1:5174/demo page for all six time-compressed synthetic scenarios. Repeated matching alerts show existing case IDs.
- Compiled ESP32 simulated and physical-sensor profiles, including MAX30102, MPU6050, AD8232, DS18B20, OLED and buzzer. See firmware/README.md.

## Verification and remaining gates

Current observed results and all phase states are in docs/IMPLEMENTATION-LEDGER.md and docs/VERIFICATION.md. Automated checks cover invalid inputs, consent withdrawal, access isolation, clinical release, appointment conflicts, sensor scenarios and provider failure behavior. Test databases are isolated from your application data.

Hardware calibration/operation, live MQTT, real OCR accuracy, actual SMS/Web Push delivery, local LLM operation, a real verified doctor directory, full Marathi/Tamil translations, MIT-BIH/clinical ECG validation and production deployment remain external or later gates. No provider credentials or hardware are available here. The observed 98.125% CNN score is on synthetic fixtures only and is not medical accuracy. The requested real-dataset 96% target has not been demonstrated.

Docker API/web/Mosquitto configuration is included but container execution is not verified in this environment. The tested path is the Windows launcher and local services.

## Data and limits

The database is backend/mediassist.db by default. A random JWT secret is stored beside it unless JWT_SECRET is configured in a private .env. Account erasure cascades through current clinical records, original documents, contacts and subscriptions. Minimal opaque audit-chain metadata remains for integrity checks; separately created local backups are not automatically erased. SQL triggers/HMAC detect ordinary chain alteration, not compromise by a machine administrator holding the key. No regulatory certification is claimed.

This is preliminary decision support, not a diagnosis, emergency monitoring service or replacement for qualified care. Real deployment needs separate clinical, privacy, security and operational review. The fictional directory does not send appointments to real clinicians.

# Integration activation and honest verification limits

The normal local application needs no external hardware, broker, provider credentials or LLM. The Integrations screen distinguishes local, mock and setup-dependent paths.

| Integration | Included | Activation still needed |
|---|---|---|
| HTTP/WS sensor ingestion | Validated packets, live canvas, trends, deduplication | Physical device verification |
| MQTT | Device-scoped bridge, Compose Mosquitto profile | Running broker, credentials, network/device tests |
| OCR | Text PDF/TXT; local Tesseract image and PyMuPDF scanned-PDF adapters | Engine/language pack installation and OCR accuracy checks |
| Local NLP | Offline field extraction; strict optional loopback Ollama adapter | Runtime/model installation and evaluation |
| Translation | i18next English/Hindi fixed labels, guided templates, bounded template cache | Clinical linguistic review; full Marathi/Tamil; optional greeting model activation |
| SMS | Console mock; Twilio HTTP adapter, consent, retries | Account/sender, recipient consent, trial/region delivery checks |
| Web Push | VAPID adapter, subscription controls, safe service-worker handlers | VAPID keys/contact, optional package, browser permission, real delivery test |
| ECG model | Trainable CNN, registry, synthetic artifact/evaluation | Licensed real dataset preparation, MIT-BIH/patient-level clinical validation |
| Specialist directory | Thirty fictional profiles, distances, slots, consent sharing | Verified real provider data and external booking service |
| Firmware | Both ESP32 profiles compile, real drivers included | Physical wiring, calibration, acquisition timing and safety checks |

## MQTT

```powershell
.\\.venv\\Scripts\\python.exe -m pip install -r integrations/requirements.txt
$env:MQTT_HOST='127.0.0.1'
$env:MQTT_PORT='1883'
$env:MQTT_DEVICE_ID='esp32-demo'
$env:MEDIASSIST_API='http://127.0.0.1:8010'
# Set MEDIASSIST_PATIENT_TOKEN locally to a valid patient JWT.
.\\.venv\\Scripts\\python.exe integrations/mqtt_bridge.py
```

The bridge accepts only mediassist/{device_id}/vitals, /ecg and /events. Payloads use backend/ingestion.py's SensorPacket schema. Event IDs must be unique across boots/runs. The authenticated API rejects duplicate IDs, invalid values and withdrawn consent. MQTT_USERNAME, MQTT_PASSWORD and MQTT_TLS configure optional authenticated/TLS transport. The firmware's default transport is private development WiFiClient; production TLS remains a separate deployment task. The Compose broker profile is not an authentication-ready production broker.

## OCR and local models

Install the Tesseract executable and English language data separately; configure TESSERACT_CMD in .env. Scanned PDF rendering additionally requires:

```powershell
.\\.venv\\Scripts\\python.exe -m pip install -r backend/requirements-ocr.txt
```

Text PDFs use pypdf. Up to 30 text pages, 5 scanned pages and 5 MB per upload are accepted. OCR uses local temporary files, a bounded subprocess and no shell. Report values and units must always be checked against the original; no OCR accuracy is established here.

Optional field extraction uses OLLAMA_ENABLED=1, OLLAMA_URL=http://127.0.0.1:11434 and a locally installed OLLAMA_MODEL. Ranked condition hypotheses require the separate OLLAMA_ASSESSMENT_ENABLED=1 opt-in and remain held for the assigned doctor; the model cannot lower rule urgency. Only loopback destinations are accepted. Invalid/unavailable output falls back to deterministic extraction; emergency rules run first. Optional OLLAMA_TRANSLATION_ENABLED=1 is restricted to registered public greetings. Arbitrary health text is refused by the translation API and never put into its cache.

## Notifications

Default SMS_PROVIDER=console records emergency mock messages locally. No external transmission occurs. A real Twilio configuration needs SMS_PROVIDER=twilio, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM in .env, plus explicit emergency-contact consent in Privacy & settings. The adapter follows [Twilio's message resource](https://www.twilio.com/docs/messaging/api/message-resource). A provider-accepted response is recorded as accepted, not delivered. Definite HTTP rejection retries at most three attempts; network ambiguity is held as delivery_unknown for provider-history inspection. Contact changes cancel earlier pending messages. Consent withdrawal stops delivery; contact consent can still be removed while health processing is paused.

Web Push requires backend/requirements-notifications.txt, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_CONTACT=mailto:YOUR_CONTACT. The patient explicitly clicks Enable browser notifications and grants browser permission. Only a generic availability notice is displayed; symptoms and report values are not placed in browser notifications. The contact, subscription and outbox data cascade on account erasure. Browser permissions themselves are controlled by the browser.

No live SMS or push message was sent in this session. Transport failures/success responses were tested using mocks. Real delivery remains unverified.

## Firmware and models

See firmware/README.md and docs/PHASE-9-RESULTS.md for compiled profiles and hardware limits. Model artifacts, split metadata and confusion matrix are in models/ecg-demo; cards are in docs/model-cards. The synthetic score is not clinical accuracy and does not satisfy a real-dataset medical-performance target.

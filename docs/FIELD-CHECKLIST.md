# Field and workflow verification map

This map lists the current constraints and evidence sources. Automated API/helper tests and observed browser flows are distinguished; these checks do not establish clinical accuracy for arbitrary patient inputs.

| Form / fields | Constraints and behavior | Verification |
|---|---|---|
| Login email/password | Credentials unchanged; email normalized; incorrect credentials vs unavailable API vs expired session distinguished | test_api, test_regressions, http.test; actual patient/GP login |
| Registration name/email/password/consent | Trimmed name 2–100; email shape/uniqueness; password 10–200; explicit consent; patient role only | API regression tests |
| Account/session | JWT expiry/revocation, per-account state reset, patient/assigned-doctor/admin restrictions | test_foundation, test_regressions; browser sign-in/out |
| Guided symptoms | 3–3000 characters; emergency check before question/model handling | test_conversation; browser six-question intake |
| Guided age | Whole years 1–120; no inferred age stored as an answer | test_conversation; browser age field |
| Duration | Nonblank, up to 100 characters | helper/API tests; browser answer |
| Severity | Integer 1–10 | helper/API tests; browser answer |
| Associated symptoms | Required answer, up to 3000; explicit none permitted | test_conversation; browser answer |
| Conditions/medicines/allergies | Required answer, up to 3000; explicit none permitted | test_conversation; browser answer |
| Optional speech | Explicit service notice; typed fallback; microphone denial handled | source/browser capability checks; actual microphone service unavailable |
| Optional model hypotheses | Loopback opt-in only, strict ranked schema, no urgency override, emergency bypass, offline fallback, held until doctor | test_assessment_model and test_conversation; no live model |
| Report paste | 3–30000 characters; original text/values/units retained | test_reports_extended; browser default four values |
| Report file | TXT/PDF/PNG/JPEG, signature/size checks, max 5 MB; text PDF 30 pages, scanned 5 pages; missing OCR setup is actionable | test_regressions, test_reports_extended; upload API and protected downloads |
| Report ranges/units | Printed interval overrides example only when valid; unfamiliar units/reversed/nonfinite ranges need review; no numeric conversions | extended/parser tests; browser flags and Hindi labels preserve values |
| Search city/specialty/language | Combined filtering, empty-state behavior | test_referrals; browser combined filters |
| Near city/radius | Both coordinates, finite bounds; radius 1–5000km; Haversine checked; approximate city centres disclosed | test_referrals; browser 0km Mumbai result |
| Availability date | Valid date/90-day horizon; only future open clinic slots | booking regression/referral tests |
| Booking date/time | Separate date/24-hour IST time, half-hour 09:00–17:30, no past/blocked/occupied slots, atomic conflict handling | API conflict tests; browser 12:30 booking |
| Sharing checkbox | Optional; cannot restore withdrawn account consent; selected clinician access ends on cancellation/revocation | consent-sharing tests; browser unchecked booking shown correctly |
| Cancellation | History retained; slot available again | test_regressions; browser cancellation success |
| Clinician availability | Own profile only; future valid slot; reason 5–200; cannot silently remove booked slot; reopen supported | test_referrals; frontend build |
| Review action/note/final guidance | Five actions; note 5–2000; edited guidance 5–3000 for edit-and-approve; only assigned doctor may approve | test_review_workflow; browser edited approval and automatic patient release |
| Information-request reply | Owner with consent, 3–3000 text, only needs_info cases, original unchanged, new review clock, emergency phrases immediate | test_followups; browser request → reply → doctor view → approval |
| Rejected/escalated/expired | Clear outcome and doctor note; unapproved hypotheses remain held | follow-up/review tests |
| Contact name/phone/consent | Name up to100; E.164 +country number; explicit consent; changes cancel pending messages; withdrawal allowed while health processing paused | test_phase8, test_final_workflows; browser mock setup/preferences |
| Push opt-in | Disabled without configuration; permission only after user action; HTTPS supported endpoints/keys validated; disable supported | adapter/PWA tests; browser disabled setup control; no real push activation |
| Language | Fixed English/Hindi keys, guided/emergency/report templates, original clinical text retained; Marathi/Tamil fallback metadata | i18n.test, language API tests; Hindi browser screenshots |
| Sensor kind/IDs/time | Kind-specific required fields; IDs 1–100; finite Unix time, at most60sec future; persistent per-user/device/event deduplication | test_ingestion, test_devices, regression tests |
| HR/SpO2/temperature | 25–250bpm, 50–100%, 30–45°C; no NaN/infinity; duration/activity rules and personal baseline | detection/ingestion tests; live browser simulator |
| ECG samples/rate | Finite numeric list 25–7200, 250/360Hz, 250Hz resampling, user/device isolation and sample-aligned context | ingestion, detection, final_workflows; browser canvas |
| Acceleration/events | Numeric magnitude or complete xyz, raw/linear tag, fall impact + stillness, disconnected leads produce no fake measurements | detection, ingestion, firmware-contract tests; six-scenario browser replay |
| Notifications/read state | Per-user scope; mark read; generic external payload; retry/unknown states explicit | regression/phase8 tests |
| History/export/original download | Owner scope; held outputs sanitized; metadata/contacts included; original files authenticated | regression/final_workflows tests; browser export download |
| Account erasure | Cascading clinical/document/contact/subscription removal; minimal opaque audit integrity retained; local backups separate | regression/review tests; destructive UI not used on user accounts |
| Startup/ports | One-command startup, matching API proxy, readiness/version, occupied-port errors, dependency hashes, Windows build-tool lock guard | actual isolated8011/5175 startup/shutdown; active8010/5174 health checks |
| Firmware pins/profiles | Required pinout and schema fixtures, simulator/device tags, missing reading suppression | four contract checks and both PlatformIO builds; no hardware measurements |

Backend tests use temporary databases and fictional users. The full suite's measured results, tooling scope and remaining external gates are in VERIFICATION.md.

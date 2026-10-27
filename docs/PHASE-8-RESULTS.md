# Phase 8: language, notification adapters and demo

Software gate passed on 27 October 2026: 166 backend tests plus 124 subtests, 27 frontend tests, and production build. A coverage run exposed a migration-test/background-worker isolation race; the test now passes an explicit database path. The affected 62 checks were rerun successfully.

The i18next dictionary covers all extracted fixed interface strings in English and Hindi, including form labels, consent, booking and review actions. Guided questions and emergency templates are translated; Hindi red-flag phrases bypass model calls. Marathi/Tamil resource metadata and fallback are present but their translations remain pending. Original lab text, clinical notes and user free text stay in the original language. Clinician linguistic validation is still needed.

Emergency contact preferences validate international phone numbers. SMS defaults to a local mock. Twilio and Web Push adapters require explicit configuration and recipient/browser consent. Consent is rechecked before dispatch; changing contact cancels queued messages. Definite provider rejection has bounded retries; an ambiguous timeout is held as delivery_unknown to prevent blind duplicate sending. Provider acceptance is not labelled recipient delivery. Tests use mocked transports: no external messages were sent.

The hidden /demo page replays all six synthetic scenarios with compressed measurement timestamps. Browser verification showed all six results and a detected impact/stillness event. New abnormal reasons are no longer suppressed by an unrelated earlier alert. Repeated replays coalesce matching recent cases. The clinician WebSocket reconnects after service restart.

A bounded translation cache accepts registered templates only. Optional loopback model translation is limited to a public greeting; health text is rejected. No local model/provider/hardware is available for activation tests.

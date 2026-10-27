# Phase 2 gate: passed for local software
- 112 backend checks passed, plus 124 subtests.
- 29 signal/schema tests include 250/360 Hz timing, 7 Hz preservation and 150 Hz alias attenuation. The resampler is NumPy-only windowed sinc; no SciPy dependency is hidden.
- Canonical authenticated HTTP/MQTT packet schema, persisted deduplication, user-scoped WebSocket fan-out, ECG packets and recorded 24-hour hourly trends are implemented.
- Browser registration with a separate fictional QA account succeeded. The simulator produced actual 250 Hz packets, a rendered ECG waveform, connected WebSocket status and recorded trends. Simulation stopped cleanly.
- Frontend/API now both run from the selected existing folder, using API8010 and website5174.
- Offline service worker only caches public shell assets. API and health records are excluded.
- Live MQTT broker and physical sensors are unavailable; bridge contract checks are software-only.
- Screenshot: phase2-live.png.

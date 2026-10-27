# Phase 7: specialist directory and bookings

Passed locally on 27 October 2026. The regression suite reached 150 tests plus 124 subtests, followed by one additional passing consent-sharing test (151 backend tests in total). The frontend production build passed.

- Haversine calculations checked against zero distance and a known one-degree distance.
- Combined city, specialty, language, radius and date filters work. Coordinates are approximate city centres.
- Assigned clinicians can block and reopen their own future clinic slots. Booked or blocked slots cannot be booked twice, including through direct API requests.
- Selected appointment clinicians can download original reports only while the booking and explicit sharing consent are active; cancellation revokes access.
- Clinician overview shows its own review queue and appointment availability.

All 30 profiles are fictional demonstration data. No real doctor verification or external appointment-provider transaction has been claimed.

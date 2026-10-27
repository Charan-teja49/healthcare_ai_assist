# Local demonstration and repeatable browser test

The website and API must be running from this project on ports 5174 and 8010. All example health data is fictional. External providers remain disabled.

1. Sign in as a patient and open http://127.0.0.1:5174/demo . Select Run all six scenarios. Replay uses compressed measurement timestamps, so the ten-second persistence rules can be demonstrated quickly.
2. Verify six completed result lines: normal rest, arrhythmia episode, low SpO2, fever, fall and leads off. Impact/stillness and lead loss are shown explicitly. Matching recent alerts coalesce, and recent case IDs explain zero new cases on a repeat run.
3. Open Symptom checker → Start guided intake. Answer symptoms, age, duration, severity, associated symptoms and existing conditions. The ordinary result stays held for the assigned doctor.
4. In another browser session, sign in as doctor@demo.local. Open Doctor review, find the fictional case, choose Edit & approve and provide a note plus final guidance. Save.
5. The patient's open conversation releases the edited guidance. Cardiovascular sensor alerts appear in cardio@demo.local's queue; general/fall cases appear in the GP queue.
6. Switch Language to Hindi and verify labels/questions. Original submissions and clinical notes retain their original language. The browser's own date widgets may follow its locale.

## Playwright runner

A reusable test is frontend/e2e/demo.spec.ts. It creates a fictional local patient and leaves its demonstration history for inspection. It does not contact external SMS providers.

```powershell
npm.cmd --prefix frontend exec -- playwright install chromium
npm.cmd --prefix frontend run e2e
```

The test times the complete six-scenario and clinician-release sequence and asserts it is under three minutes. This session used the connected browser's Playwright controls for the observed workflow; the standalone runner is provided separately. Consult docs/VERIFICATION.md for exactly which execution paths were observed.

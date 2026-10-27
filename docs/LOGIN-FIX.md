# Login fix — v0.2.1

The observed page showed `Failed to fetch`, not an incorrect-password response. Direct demo login to the running backend succeeded. The frontend port 5174 was not listening, while an original v0.1 Desktop copy still served the backend on port 8000.

The active Desktop project was backed up, its database was preserved, its source/packages were updated, and matching services were started. Browser sign-in at port 5174 then reached the patient dashboard. Health-processing consent was preserved as withdrawn; it does not prevent login.

Additional corrections:

- Proxy/server failures are distinguished from invalid credentials, consent errors and field validation errors.
- Demo account buttons reset both email and password, rather than keeping a previously typed incorrect password.
- The launcher prefers the project virtual environment and verifies that Python can actually execute.
- The health endpoint identifies the application version.

Verification: 60 backend tests passed in the active Desktop Python environment; 21 frontend tests passed, including 11 response/error regression tests and the demo-credential reset check. The production frontend build passed. Actual browser login was verified with the preserved database.

Start both services from the project folder with `powershell -ExecutionPolicy Bypass -File .\start.ps1`, and keep the terminal running. If either service is stopped, an already-loaded page can remain visible but cannot submit requests. The updated connection message explains how to recover.

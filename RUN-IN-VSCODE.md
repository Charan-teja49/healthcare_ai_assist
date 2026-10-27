# Continue in the existing VS Code folder

Open this folder directly:

C:\\Users\\chara\\OneDrive\\Desktop\\MediAssist-AI-v0.2.1-Login-Fixed\\mediassist

No new archive or project copy is required. Open Terminal → New Terminal and use PowerShell.

## One-command startup

```powershell
powershell -ExecutionPolicy Bypass -File .\\start.ps1 -Reload
```

The website is http://127.0.0.1:5174 and API docs are http://127.0.0.1:8010/docs . Keep the terminal open. Ctrl+C stops this launch. -Reload reloads backend source changes; the website reloads during development automatically.

If the ports already run this project, use that website. Stop the existing server terminal before starting another instance. Do not kill unrelated processes or change random ports to hide a duplicate-server problem.

## Two terminals, when preferred

Both start in the mediassist folder. First setup only:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r .\\backend\\requirements-lock.txt
npm.cmd --prefix frontend ci
```

Terminal 1:

```powershell
.\\.venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload --reload-dir backend --reload-exclude "test_*.py" --host 127.0.0.1 --port 8010
```

Terminal 2:

```powershell
npm.cmd --prefix frontend run dev -- --port 5174
```

After setup, skip environment creation and installation unless dependencies change. Use npm.cmd if PowerShell blocks npm.ps1.

## Checks

```powershell
.\\.venv\\Scripts\\python.exe -m pip install -r backend/requirements-dev.txt
.\\.venv\\Scripts\\python.exe -m pytest backend --cov=backend --cov-report=term-missing
.\\.venv\\Scripts\\python.exe -m ruff check backend
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
```

Type checking covers the typed scenario/sensor contracts and their demo component; the older application screens are JavaScript and are checked by ESLint, runtime tests and browser workflows. The reusable Playwright test and its run instructions are in docs/DEMO-WALKTHROUGH.md.

## Login and submission recovery

- Use one of the four demo emails and Demo@12345, or your registered patient credentials.
- An incorrect-password response differs from an unavailable API. Connection errors include startup guidance.
- If health processing is paused, enable it explicitly in the banner. Appointment sharing does not restore account consent.
- Bookings use future available half-hour times from 09:00 through 17:30 in India time, within 90 days. Blocked or occupied times are rejected by the API too.
- Image/scanned-PDF extraction reports missing OCR setup. Paste text or use a readable PDF until the optional engines are installed.
- Backend startup diagnostics are in backend-errors.log. The current app version is returned by /api/health.

Optional adapter setup is in docs/INTEGRATIONS.md. Never paste provider secrets into chat or commit them to source.

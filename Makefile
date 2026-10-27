PYTHON ?= python
api:
	$(PYTHON) -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
test:
	$(PYTHON) -m pytest backend -q
web:
	cd frontend && npm run dev
build:
	cd frontend && npm run build

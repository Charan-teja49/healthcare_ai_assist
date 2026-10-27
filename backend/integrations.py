"""Optional local integrations. No patient data is sent to outside services by default."""

import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import HTTPException


def tesseract_path():
    configured = os.getenv("TESSERACT_CMD", "")
    return (configured if Path(configured).is_file() else None) or shutil.which(
        "tesseract"
    )


def extract_image_text(content, suffix):
    executable = tesseract_path()
    if not executable:
        raise HTTPException(
            503,
            "Image OCR needs Tesseract. Configure TESSERACT_CMD, or paste text / upload a text PDF instead.",
        )
    if not (
        content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\xff\xd8\xff")
    ):
        raise HTTPException(422, "File contents do not match a PNG or JPEG image.")
    with tempfile.TemporaryDirectory(prefix="mediassist-ocr-") as folder:
        source = Path(folder) / ("report" + suffix)
        source.write_bytes(content)
        try:
            response = subprocess.run(
                [executable, str(source), "stdout", "-l", "eng"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise HTTPException(
                422,
                "OCR failed. Ensure English language data is installed, or paste the report text.",
            )
    return response.stdout


def status():
    from backend.notification_dispatch import push_ready, sms_ready

    return [
        {
            "name": "HTTP sensor ingestion",
            "state": "ready",
            "detail": "Authenticated /api/devices/ingest for vitals, ECG and events; persistent validation and deduplication.",
        },
        {
            "name": "Live sensor simulator",
            "state": "ready",
            "detail": "Six scenarios over server-sent events. No physical wearable required.",
        },
        {
            "name": "Rolling baseline anomaly detection",
            "state": "ready",
            "detail": "30-reading statistical baseline after 10 samples. Educational thresholds, not a trained clinical model.",
        },
        {
            "name": "In-app notifications",
            "state": "ready",
            "detail": "Booking, triage, alert, review and timeout notifications stored locally.",
        },
        {
            "name": "SMS fallback",
            "state": "configured" if sms_ready() else "mock",
            "detail": "Local mock by default. Twilio adapter requires explicit recipient consent, configuration and provider testing. Definite rejections retry at most three times; ambiguous delivery is held for inspection.",
        },
        {
            "name": "Web Push",
            "state": "configured" if push_ready() else "needs setup",
            "detail": "VAPID, optional pywebpush and explicit browser opt-in required. Only generic notifications are displayed.",
        },
        {
            "name": "Image OCR",
            "state": "configured" if tesseract_path() else "needs setup",
            "detail": "PNG/JPEG extraction via local Tesseract. Confirm all extracted values against the original.",
        },
        {
            "name": "MQTT device bridge",
            "state": "available" if importlib.util.find_spec("paho") else "needs setup",
            "detail": "Run integrations/mqtt_bridge.py with a broker, patient token and device ID. It forwards to the validated HTTP API.",
        },
        {
            "name": "ESP32 firmware",
            "state": "source included",
            "detail": "Both ESP32 simulator and physical-sensor profiles compiled. Wiring, acquisition timing and calibration require hardware validation.",
        },
        {
            "name": "Voice symptom intake",
            "state": "browser dependent",
            "detail": "Opt-in browser speech recognition; typed intake is always available. Browser may use its speech service.",
        },
        {
            "name": "Local NLP extraction",
            "state": "configured"
            if os.getenv("OLLAMA_ENABLED") == "1"
            else "offline fallback",
            "detail": "Offline field extraction and optional loopback-only Ollama adapters. Ranked hypotheses require separate opt-in and stay held for the assigned doctor. Emergency rules run first.",
        },
        {
            "name": "Research ECG classifier",
            "state": "synthetic demo only",
            "detail": "Trainable NumPy Conv1D model and held-out synthetic evaluation included. Real-device inference is disabled. No MIT-BIH or clinical accuracy claim.",
        },
        {
            "name": "Multilingual UI",
            "state": "English / Hindi templates",
            "detail": "Translated fixed interface labels and guided questions; Marathi/Tamil resource structure ready. Original reports, doctor notes and free text are preserved, not automatically translated.",
        },
    ]

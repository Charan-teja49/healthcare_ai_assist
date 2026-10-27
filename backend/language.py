"""Bounded translation of registered templates only; no health text enters the cache."""

import json
import os
from functools import lru_cache
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field


def require_user(auth=Depends(HTTPBearer())):
    from backend.main import current

    return current(auth)


router = APIRouter()
HINDI = {
    "Describe the symptoms you are experiencing.": "आपको कौन से लक्षण महसूस हो रहे हैं?",
    "What is your age in completed years?": "आपकी आयु पूरे वर्षों में कितनी है?",
    "How long have you had these symptoms?": "ये लक्षण कब से हैं?",
    "How severe are they from1(mild) to10(severe)?": "लक्षण कितने गंभीर हैं? 1 हल्का और 10 बहुत गंभीर है।",
    "Any other symptoms? Write none if there are no others.": "क्या अन्य लक्षण भी हैं? अगर नहीं, तो नहीं लिखें।",
    "Any existing medical conditions, pregnancy, regular medicines or allergies? Write none if there are none.": "क्या कोई पुरानी बीमारी, गर्भावस्था, नियमित दवा या एलर्जी है? अगर नहीं, तो नहीं लिखें।",
    "Submitted to your assigned doctor.": "आपके नियुक्त डॉक्टर को भेजा गया।",
    "Emergency guidance applies now; do not wait for review.": "आपातकालीन सलाह तुरंत लागू है; समीक्षा का इंतज़ार न करें।",
    "Emergency guidance applies now; seek immediate care.": "आपातकालीन सलाह तुरंत लागू है; तुरंत चिकित्सा लें।",
    "Your preliminary assessment is awaiting the assigned doctor. Seek in-person care promptly if symptoms worsen.": "आपका प्रारंभिक आकलन नियुक्त डॉक्टर की प्रतीक्षा में है। लक्षण बिगड़ने पर तुरंत व्यक्तिगत चिकित्सा लें।",
    "Seek emergency medical care now. Call your local emergency service. Do not wait for an online review.": "अभी आपातकालीन चिकित्सा लें। स्थानीय आपात सेवा को कॉल करें। ऑनलाइन समीक्षा का इंतज़ार न करें।",
    "Emergency care": "आपातकालीन चिकित्सा",
    "General physician": "सामान्य चिकित्सक",
    "Arrange an in-person assessment promptly.": "शीघ्र व्यक्तिगत चिकित्सा जाँच कराएँ।",
    "Welcome to MediAssist": "MediAssist में स्वागत है",
}
# Only this public nonclinical template may use an optional local model.
PUBLIC_MODEL_TEMPLATES = {"Welcome to MediAssist"}


@lru_cache(maxsize=128)
def translate_template(text, language="en"):
    if language == "en":
        return text
    if language == "hi" and text in HINDI:
        return HINDI[text]
    if (
        text not in PUBLIC_MODEL_TEMPLATES
        or language not in ("hi", "mr", "ta")
        or os.getenv("OLLAMA_TRANSLATION_ENABLED") != "1"
    ):
        return text
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        return text
    request = Request(
        base.rstrip("/") + "/api/generate",
        data=json.dumps(
            {
                "model": os.getenv("OLLAMA_MODEL", "llama3.2"),
                "prompt": "Translate this public interface greeting into "
                + {"hi": "Hindi", "mr": "Marathi", "ta": "Tamil"}[language]
                + ". Return only JSON with a text field. Greeting: "
                + text,
                "format": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                "stream": False,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
        translated = json.loads(result["response"])["text"]
        return (
            translated
            if isinstance(translated, str) and 1 <= len(translated) <= 200
            else text
        )
    except Exception:
        return text


class TemplateRequest(BaseModel):
    text: str = Field(max_length=500)
    language: str = Field(pattern="^(en|hi|mr|ta)$")


@router.post("/api/language/template")
def template(body: TemplateRequest, user=Depends(require_user)):
    if body.text not in HINDI:
        raise HTTPException(
            422,
            "Only registered public templates can be translated; patient text is not accepted",
        )
    return {
        "text": translate_template(body.text, body.language),
        "language": body.language,
        "mode": "registered template; optional local model for public greetings only",
    }

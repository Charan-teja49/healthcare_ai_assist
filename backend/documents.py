"""Bounded local report extraction and permission-scoped original documents."""

import io
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from fastapi.security import HTTPBearer
from pypdf import PdfReader

router = APIRouter()


def setup(c):
    c.execute(
        "CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,filename TEXT,mime TEXT,content BLOB,created REAL)"
    )


def extract(content, filename):
    from backend.integrations import extract_image_text

    if content.startswith(b"%PDF"):
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise ValueError("encrypted")
            if len(reader.pages) > 30:
                raise HTTPException(422, "Text PDFs are limited to30 pages")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "Invalid or encrypted PDF")
        if len(text.strip()) >= 3:
            return text, "application/pdf"
        if len(reader.pages) > 5:
            raise HTTPException(422, "Scanned PDFs are limited to5 pages")
        from backend.integrations import tesseract_path

        if not tesseract_path():
            raise HTTPException(
                503,
                "Scanned PDF OCR needs local Tesseract and PyMuPDF. Paste text or upload a readable PDF instead.",
            )
        try:
            import pymupdf
        except ImportError:
            raise HTTPException(
                503,
                "Scanned PDF OCR needs PyMuPDF. Install backend/requirements-ocr.txt.",
            )
        document = pymupdf.open(stream=content, filetype="pdf")
        pages = []
        try:
            for page in document:
                scale = min(
                    2.0, (2_000_000 / max(page.rect.width * page.rect.height, 1)) ** 0.5
                )
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                pages.append(extract_image_text(pix.tobytes("png"), ".png"))
        finally:
            document.close()
        return "\n".join(pages), "application/pdf"
    if filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return extract_image_text(
            content, Path(filename).suffix
        ), "image/png" if content.startswith(b"\x89PNG") else "image/jpeg"
    if filename.lower().endswith(".txt"):
        try:
            return content.decode("utf-8-sig"), "text/plain"
        except UnicodeDecodeError:
            raise HTTPException(422, "Text files must use UTF-8 encoding")
    raise HTTPException(
        422,
        "Supported formats: readable PDF, scanned PDF with OCR setup, PNG/JPEG or UTF-8 text",
    )


def current_user(auth=Depends(HTTPBearer())):
    from backend.main import current

    return current(auth)


@router.get("/api/reports/documents/{document_id}")
def original(document_id: int, user=Depends(current_user)):
    from backend.main import db

    with db() as c:
        row = c.execute(
            "SELECT d.*,u.consent,c.clinician_id FROM documents d JOIN users u ON u.id=d.user_id LEFT JOIN cases c ON c.id=d.case_id WHERE d.id=?",
            (document_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Document not found")
    shared = False
    if user["role"] == "doctor" and row["consent"]:
        with db() as c:
            shared = bool(
                c.execute(
                    "SELECT 1 FROM appointments WHERE user_id=? AND share=1 AND status='booked' AND doctor_id IN (SELECT doctor_id FROM clinician_profiles WHERE user_id=?)",
                    (row["user_id"], user["id"]),
                ).fetchone()
            )
    allowed = (
        user["role"] == "patient"
        and row["user_id"] == user["id"]
        or user["role"] == "doctor"
        and row["consent"]
        and (row["clinician_id"] == user["id"] or shared)
    )
    if not allowed:
        raise HTTPException(
            403, "Only the owner or consented assigned doctor may open this report"
        )
    safe_name = (
        Path(row["filename"]).name.replace('"', "").replace("\r", "").replace("\n", "")
    )
    return Response(
        bytes(row["content"]),
        media_type=row["mime"],
        headers={
            "Content-Disposition": "attachment; filename=\"report-original\"; filename*=UTF-8''"
            + quote(safe_name),
            "X-Content-Type-Options": "nosniff",
        },
    )

"""Extraction stage: raw PDF bytes -> clean transcript text.

The hardest real-world problem: concall PDFs often use custom/CID fonts with no
usable text layer, so a plain text extract yields garbage. Production should use
Azure Document Intelligence / AWS Textract with a Tesseract OCR fallback.

Providers (settings.extraction_provider):
* stub          - returns the bytes decoded as UTF-8 (for .txt test fixtures)
* pdfplumber    - extract embedded text layer
* azure_docintel- call Azure Document Intelligence (requires SDK + creds)
"""
from __future__ import annotations

import io

from app.config import settings


def _extract_pymupdf(data: bytes) -> str:
    import fitz  # pymupdf

    parts: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            parts.append(page.get_text())
    return "\n".join(parts)


def _extract_pdfplumber(data: bytes) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _extract_azure_docintel(data: bytes) -> str:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    client = DocumentIntelligenceClient(
        endpoint=settings.azure_docintel_endpoint,
        credential=AzureKeyCredential(settings.azure_docintel_api_key),
    )
    poller = client.begin_analyze_document("prebuilt-read", body=data)
    result = poller.result()
    return result.content or ""


def extract_text(data: bytes, *, filename: str = "") -> str:
    """Return clean text for a transcript. Falls back gracefully."""
    provider = settings.extraction_provider
    if filename.lower().endswith(".txt") or provider == "stub":
        return data.decode("utf-8", errors="replace")
    if provider == "azure_docintel":
        return _extract_azure_docintel(data)
    if provider == "pdfplumber":
        text = _extract_pdfplumber(data)
    else:
        # default: pymupdf (best general-purpose text layer extraction)
        text = _extract_pymupdf(data)
    # Heuristic: if the text layer is unusable (mostly non-letters), signal caller.
    letters = sum(c.isalpha() for c in text)
    if len(text) > 0 and letters / max(len(text), 1) < 0.3:
        # In production: fall back to OCR here (pytesseract on rasterized pages).
        text = f"[WARN: low-quality text layer, OCR fallback recommended]\n{text}"
    return text

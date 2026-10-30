"""PDF text extraction with pdfplumber, cached on disk by file sha256.

pdfplumber is used (not pypdf) because it keeps word spacing intact on the Legislative Department
PDFs ("presented", not "prese nted"), and ``dedupe_chars`` removes the overprinted (fake-bold)
text found in some High Court PDFs ("TTTTAAAA" -> "TA").
"""

import hashlib
import json
from pathlib import Path

import structlog

from app.ingestion.models import Page

logger = structlog.get_logger(__name__)

# Bump when extraction logic changes so stale caches are ignored.
EXTRACTOR_VERSION = "pdfplumber-dedupe-1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_pages(
    path: Path, cache_dir: Path | None = None, sha256: str | None = None
) -> list[Page]:
    """Return the text of every page. Uses ``cache_dir/<sha256>.json`` when available."""
    sha = sha256 or sha256_file(path)
    cache_file = cache_dir / f"{sha}.json" if cache_dir else None
    if cache_file and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("extractor") == EXTRACTOR_VERSION:
            return [Page.model_validate(p) for p in cached["pages"]]

    import pdfplumber  # optional dependency (`ingest` extra); imported lazily

    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = page.dedupe_chars().extract_text() or ""
            pages.append(Page(number=number, text=text))
    logger.info("pdf_extracted", path=str(path), pages=len(pages))

    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"extractor": EXTRACTOR_VERSION, "pages": [p.model_dump() for p in pages]}
        cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return pages

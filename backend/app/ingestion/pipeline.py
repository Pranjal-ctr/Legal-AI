"""End-to-end ingestion: statutes + judgments -> documents.jsonl, chunks.jsonl, manifest, report."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from app.ingestion.corpus import discover_judgments
from app.ingestion.judgment import build_judgment
from app.ingestion.models import Chunk, Document, SourceFile
from app.ingestion.pdf import EXTRACTOR_VERSION, extract_pages, sha256_file
from app.ingestion.statute import HMA_1955, ActSpec, build_statute

logger = structlog.get_logger(__name__)

# Statute PDFs, relative to the data dir. Provenance is recorded in CLAUDE.md ("Source corpus").
STATUTES: list[tuple[ActSpec, str]] = [(HMA_1955, "raw/hma1955.pdf")]

# Where each part of the corpus was obtained (as stated by the corpus owner).
ORIGINS = {
    "statute": "Legislative Department text (High Court of Punjab & Haryana mirror)",
    "supreme_court": "Digital Supreme Court Reports, digiscr.sci.gov.in",
    "high_court": "eCourts judgments portal, judgments.ecourts.gov.in",
}


@dataclass(frozen=True)
class IngestPaths:
    repo_root: Path
    data_dir: Path

    @property
    def dataset_dir(self) -> Path:
        return self.data_dir / "family_law_dataset"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def cache_dir(self) -> Path:
        return self.processed_dir / "text_cache"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"


@dataclass
class IngestResult:
    documents: list[Document] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def ingest(paths: IngestPaths, use_cache: bool = True) -> IngestResult:
    result = IngestResult()
    cache = paths.cache_dir if use_cache else None

    for spec, rel_path in STATUTES:
        pdf = paths.data_dir / rel_path
        if not pdf.exists():
            result.warnings.append(f"{spec.act_id}: statute PDF missing at {pdf}")
            continue
        sha = sha256_file(pdf)
        source = SourceFile(
            path=_rel(pdf, paths.repo_root), sha256=sha, size_bytes=pdf.stat().st_size
        )
        document, chunks = build_statute(extract_pages(pdf, cache, sha), spec, [source])
        result.documents.append(document)
        result.chunks.extend(chunks)

    for entry in discover_judgments(paths.dataset_dir, paths.repo_root):
        pages = extract_pages(paths.repo_root / entry.primary_path, cache, entry.sha256)
        document, chunks = build_judgment(
            pages, entry.doc_id, entry.court_level, entry.topics, entry.sources
        )
        result.documents.append(document)
        result.chunks.extend(chunks)
        missing = [
            name
            for name, value in (
                ("court", document.court),
                ("decision_date", document.decision_date),
                ("citation/case_number", document.citation or document.case_number),
            )
            if value is None
        ]
        if missing:
            result.warnings.append(
                f"{entry.doc_id} ({entry.primary_path}): missing {', '.join(missing)}"
            )
        if any(c.chunk_id.endswith(":text") or ":text." in c.chunk_id for c in chunks):
            result.warnings.append(f"{entry.doc_id}: no numbered paragraphs, used window chunks")

    ids = [c.chunk_id for c in result.chunks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate chunk ids: {sorted(duplicates)[:10]}")
    return result


def _manifest(result: IngestResult) -> dict[str, object]:
    return {
        "extractor": EXTRACTOR_VERSION,
        "origins": ORIGINS,
        "documents": [
            {
                "doc_id": d.doc_id,
                "doc_type": d.doc_type,
                "court_level": d.court_level,
                "title": d.title,
                "court": d.court,
                "citation": d.citation,
                "decision_date": d.decision_date.isoformat() if d.decision_date else None,
                "topics": d.topics,
                "page_count": d.page_count,
                "sources": [s.model_dump() for s in d.sources],
            }
            for d in result.documents
        ],
    }


def write_outputs(result: IngestResult, paths: IngestPaths) -> dict[str, object]:
    paths.processed_dir.mkdir(parents=True, exist_ok=True)
    with (paths.processed_dir / "documents.jsonl").open("w", encoding="utf-8") as fh:
        for document in result.documents:
            fh.write(document.model_dump_json() + "\n")
    with (paths.processed_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in result.chunks:
            fh.write(chunk.model_dump_json() + "\n")
    paths.manifest_path.write_text(
        json.dumps(_manifest(result), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    by_kind: dict[str, int] = {}
    for chunk in result.chunks:
        by_kind[chunk.kind] = by_kind.get(chunk.kind, 0) + 1
    lengths = sorted(len(c.text) for c in result.chunks)
    report: dict[str, object] = {
        "documents": len(result.documents),
        "statutes": sum(d.doc_type == "statute" for d in result.documents),
        "judgments": sum(d.doc_type == "judgment" for d in result.documents),
        "chunks": len(result.chunks),
        "chunks_by_kind": by_kind,
        "chunk_chars": {
            "min": lengths[0] if lengths else 0,
            "median": lengths[len(lengths) // 2] if lengths else 0,
            "max": lengths[-1] if lengths else 0,
        },
        "warnings": result.warnings,
    }
    (paths.processed_dir / "ingest_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    logger.info("ingest_written", **{k: v for k, v in report.items() if k != "warnings"})
    return report

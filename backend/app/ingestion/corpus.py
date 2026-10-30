"""Discover the judgment corpus on disk and collapse byte-identical duplicates.

Expected layout (``data/family_law_dataset``)::

    supreme court judgements/<topic>/<file>.pdf
    high court judgements/<topic>/<file>.pdf
    acts and laws/...                      (statutes; parsed separately)

The same PDF filed under two topics (e.g. a divorce + domestic-violence judgment) becomes ONE
document carrying both topics, so retrieval never returns duplicate chunks.
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.ingestion.models import CourtLevel, SourceFile
from app.ingestion.pdf import sha256_file

COURT_FOLDERS: dict[str, CourtLevel] = {
    "supreme court judgements": "supreme_court",
    "high court judgements": "high_court",
}

# Folder names are kept as the dataset has them; topics are normalised spellings.
TOPIC_ALIASES = {"maintainence": "maintenance"}


@dataclass
class CorpusEntry:
    sha256: str
    court_level: CourtLevel
    sources: list[SourceFile] = field(default_factory=list)

    @property
    def doc_id(self) -> str:
        prefix = "sc" if self.court_level == "supreme_court" else "hc"
        return f"{prefix}-{self.sha256[:10]}"

    @property
    def topics(self) -> list[str]:
        return sorted({s.topic for s in self.sources if s.topic})

    @property
    def primary_path(self) -> str:
        return self.sources[0].path


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def discover_judgments(dataset_dir: Path, repo_root: Path) -> list[CorpusEntry]:
    """Walk the dataset; return one entry per unique file content, in a stable order."""
    entries: dict[str, CorpusEntry] = {}
    for folder, court_level in COURT_FOLDERS.items():
        base = dataset_dir / folder
        if not base.is_dir():
            continue
        for pdf in sorted(base.rglob("*.pdf")):
            topic_dir = pdf.parent.name if pdf.parent != base else None
            topic = TOPIC_ALIASES.get(topic_dir, topic_dir) if topic_dir else None
            sha = sha256_file(pdf)
            source = SourceFile(
                path=_rel(pdf, repo_root), sha256=sha, size_bytes=pdf.stat().st_size, topic=topic
            )
            entry = entries.setdefault(sha, CorpusEntry(sha256=sha, court_level=court_level))
            entry.sources.append(source)
    return sorted(entries.values(), key=lambda e: (e.court_level, e.primary_path))

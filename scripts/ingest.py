"""Ingest the corpus: ``python -m scripts.ingest [--data-dir data] [--no-cache]``.

Writes data/processed/{documents,chunks}.jsonl and ingest_report.json, and data/manifest.json
(the committed record of which source files, by sha256, make up the corpus).
"""

import argparse
import json
from pathlib import Path

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.ingestion.pipeline import IngestPaths, ingest, write_outputs


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    parser.add_argument("--no-cache", action="store_true", help="re-extract every PDF")
    args = parser.parse_args(argv)

    configure_logging(settings.log_level, settings.log_json)
    paths = IngestPaths(repo_root=Path.cwd(), data_dir=args.data_dir)
    result = ingest(paths, use_cache=not args.no_cache)
    report = write_outputs(result, paths)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

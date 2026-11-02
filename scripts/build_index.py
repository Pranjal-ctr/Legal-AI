"""Embed the ingested corpus into the vector index: ``python -m scripts.build_index``.

Reads data/processed/{documents,chunks}.jsonl (run ``python -m scripts.ingest`` first) and
writes the Qdrant collection plus data/index/index_meta.json. Stop the API server first when
using embedded Qdrant (it holds a file lock on the index).
"""

import argparse
import sys

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.rag.factory import build_embedder, build_vector_store
from app.retrieval.corpus import Corpus
from app.retrieval.index import build_index


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args(argv)

    configure_logging(settings.log_level, settings.log_json)
    corpus = Corpus.load(settings.data_dir / "processed")
    store = build_vector_store(settings)
    try:
        meta = build_index(
            corpus,
            build_embedder(settings),
            store,
            settings.index_dir,
            batch_size=args.batch_size,
            on_progress=lambda done, total: print(
                f"\rembedded {done}/{total}", end="", file=sys.stderr
            ),
        )
    finally:
        store.close()
    print(file=sys.stderr)
    print(meta.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

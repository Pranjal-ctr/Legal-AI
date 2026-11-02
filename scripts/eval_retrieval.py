"""Score retrieval on the gold queries: ``python -m scripts.eval_retrieval [--k 6]``.

Each config is ``dense``, ``bm25`` or ``hybrid``, optionally ``+rerank`` (cross-encoder order)
or ``+fuse`` (RRF of first-stage and cross-encoder orders); all configs run in one
process so models load once. Prints a comparison table and writes per-query results to
reports/retrieval_eval.json. Needs the index (``python -m scripts.build_index``); no LLM.
Use ``--language`` to score only queries of one language (e.g. ``hi``) and ``--translate`` to
also search with an LLM English translation of non-English queries (needs Ollama), as the
API does.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import cast, get_args

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.nlp.language import Language
from app.providers.translation import LLMTranslator
from app.rag.factory import build_embedder, build_llm, build_reranker, build_vector_store
from app.retrieval.corpus import Corpus
from app.retrieval.evaluation import load_gold, score_query, summarise
from app.retrieval.index import RetrievalMode, Retriever

DEFAULT_CONFIGS = "dense,bm25,hybrid,dense+rerank,hybrid+rerank,hybrid+fuse"


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=settings.retrieval_top_k)
    parser.add_argument("--configs", default=DEFAULT_CONFIGS)
    parser.add_argument("--language", default=None, help="only score gold queries in this language")
    parser.add_argument(
        "--gold", type=Path, default=settings.data_dir / "evaluation" / "gold_queries.jsonl"
    )
    parser.add_argument("--out", type=Path, default=Path("reports/retrieval_eval.json"))
    parser.add_argument("--translate", action="store_true", help="LLM-translate non-English")
    args = parser.parse_args(argv)

    configure_logging(settings.log_level, settings.log_json)
    corpus = Corpus.load(settings.data_dir / "processed")
    embedder = build_embedder(settings)
    meta = Retriever.check_ready(corpus, embedder, settings.index_dir)
    gold = [g for g in load_gold(args.gold) if args.language in (None, g.language)]
    english: dict[str, str] = {}
    if args.translate:
        translator = LLMTranslator(build_llm(settings, light=True))
        for g in gold:
            if g.language != "en":
                lang = cast(Language, g.language)
                english[g.id] = asyncio.run(translator.to_english(g.query, lang))
    store = build_vector_store(settings)
    reranker = None
    configs: dict[str, object] = {}
    table: list[str] = []
    try:
        for config in args.configs.split(","):
            mode, _, extra = config.partition("+")
            if mode not in get_args(RetrievalMode) or extra not in ("", "rerank", "fuse"):
                parser.error(f"unknown config {config!r}")
            if extra and reranker is None:
                reranker = build_reranker(settings.model_copy(update={"rerank_enabled": True}))
            retriever = Retriever(
                corpus,
                embedder,
                store,
                mode=cast(RetrievalMode, mode),
                reranker=reranker if extra else None,
                rerank_strategy="replace" if extra == "rerank" else "fuse",
                candidate_k=settings.retrieval_candidates,
            )
            results = []
            for g in gold:
                alt = [english[g.id]] if g.id in english else []
                hits = retriever.search(
                    g.query, args.k, alt_queries=alt, rerank_query=english.get(g.id)
                )
                results.append(score_query(g, [h.chunk.chunk_id for h in hits]))
            summary = summarise(results, args.k)
            configs[config] = {
                "summary": summary.model_dump(),
                "misses": [r.id for r in results if r.first_hit_rank is None],
                "results": [r.model_dump() for r in results],
            }
            table.append(
                f"{config:<16} hit={summary.hit_rate:.2f} doc_hit={summary.doc_hit_rate:.2f} "
                f"recall={summary.mean_recall:.2f} mrr={summary.mrr:.3f} "
                f"misses={[r.id for r in results if r.first_hit_rank is None]}"
            )
    finally:
        store.close()

    report = {"index": meta.model_dump(mode="json"), "translations": english, "configs": configs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"k={args.k}, queries={len(gold)}, translated={len(english)}")
    print("\n".join(table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

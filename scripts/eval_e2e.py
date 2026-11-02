"""End-to-end evaluation of the full pipeline: ``python -m scripts.eval_e2e``.

Runs every gold query through the real orchestrator (same factory as the API: index, reranker,
Ollama), with automatic language detection. When the system asks a clarifying question, it is
answered with ``religion=hindu``: the corpus is Hindu Marriage Act centred, and every gold query
concerns it. Writes per-query results and a summary to ``reports/e2e_eval.json`` and a readable
table to ``reports/e2e_eval.md``. Stop the API first (the embedded Qdrant index is file-locked).
Takes ~10-15 s per query on the reference machine.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.agents.evaluation import E2EResult, rescore, score_result, summarise
from app.agents.understanding import UserFacts
from app.core.config import load_settings
from app.core.logging import configure_logging
from app.rag.factory import build_orchestrator
from app.retrieval.evaluation import GoldQuery, load_gold

GOLD_FILES = ("gold_queries.jsonl", "gold_queries_multilingual.jsonl", "gold_queries_lay.jsonl")


async def run(gold: list[GoldQuery], out: Path) -> list[E2EResult]:
    settings = load_settings()
    orchestrator = build_orchestrator(settings)
    rows: list[E2EResult] = []
    try:
        await orchestrator.warmup()
        for i, g in enumerate(gold, start=1):
            started = time.perf_counter()
            result = await orchestrator.answer(g.query)
            clarified = result.kind == "clarification"
            if clarified:
                started = time.perf_counter()
                result = await orchestrator.answer(g.query, facts=UserFacts(religion="hindu"))
            ms = int((time.perf_counter() - started) * 1000)
            row = score_result(g, result, ms, clarified)
            rows.append(row)
            print(
                f"[{i}/{len(gold)}] {g.id:8} {row.kind:13} cite={int(row.citation_hit)} "
                f"evid={int(row.evidence_cited)} quotes={row.verified_quotes}/-{row.unquoted} "
                f"{ms / 1000:.1f}s",
                flush=True,
            )
            # incremental: a long run can be inspected while it goes
            snapshot = json.dumps([r.model_dump() for r in rows], ensure_ascii=False, indent=1)
            await asyncio.to_thread(out.write_text, snapshot, encoding="utf-8")
    finally:
        orchestrator.close()
    return rows


def _table(title: str, summary: dict[str, object]) -> list[str]:
    lines = [f"### {title}", "", "| metric | value |", "|---|---|"]
    for key, value in summary.items():
        lines.append(f"| {key} | {json.dumps(value, ensure_ascii=False)} |")
    return [*lines, ""]


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", nargs="*", type=Path, default=None)
    parser.add_argument("--language", default=None, help="only queries in this language")
    parser.add_argument("--limit", type=int, default=0, help="first N queries (smoke test)")
    parser.add_argument("--out", type=Path, default=Path("reports/e2e_eval.json"))
    parser.add_argument(
        "--rescore", type=Path, default=None, help="re-score stored results (JSON) without the LLM"
    )
    args = parser.parse_args(argv)

    configure_logging("WARNING", settings.log_json)
    paths = args.gold or [settings.data_dir / "evaluation" / name for name in GOLD_FILES]
    gold = [g for p in paths for g in load_gold(p) if args.language in (None, g.language)]
    if args.limit:
        gold = gold[: args.limit]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial = args.out.with_suffix(".partial.json")
    if args.rescore:
        data = json.loads(args.rescore.read_text(encoding="utf-8"))
        stored = data["results"] if isinstance(data, dict) else data
        by_id = {g.id: g for g in gold}
        rows = [rescore(E2EResult.model_validate(r), by_id[r["id"]]) for r in stored]
    else:
        rows = asyncio.run(run(gold, partial))

    groups: dict[str, list[E2EResult]] = {"all": rows}
    for row in rows:
        group = "lay" if row.id.startswith("l") else row.language
        groups.setdefault(group, []).append(row)
    summaries = {name: summarise(group) for name, group in groups.items()}
    args.out.write_text(
        json.dumps(
            {"summary": summaries, "results": [r.model_dump() for r in rows]},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    partial.unlink(missing_ok=True)

    md = ["# End-to-end evaluation", ""]
    for name, summary in summaries.items():
        md += _table(name, summary)
    md += ["### Misses (answered, expected source not cited)", ""]
    md += [
        f"- {r.id} ({r.language}): cited {r.cited_ids or 'nothing'}"
        for r in rows
        if r.kind == "answer" and not r.citation_hit
    ]
    args.out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summaries["all"], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

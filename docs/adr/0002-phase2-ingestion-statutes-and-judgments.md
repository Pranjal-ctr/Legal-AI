# ADR 0002 — Phase 2 ingests statutes and judgments into one chunk schema

- **Status:** Accepted (Phase 2, 2026-10-30)

## Context

Phase 0 scoped Phase 2 to "HMA 1955 + 20 gold queries". The corpus owner has since added
49 judgment PDFs (`data/family_law_dataset/`: 29 High Court and 20 Supreme Court, sorted
into child_custody / divorce / domestic_violence / maintainence folders). Supreme Court PDFs
come from Digital S.C.R. (digiscr.sci.gov.in) and High Court PDFs from the eCourts judgments
portal (judgments.ecourts.gov.in).

Findings from inspecting the files:
- All of them have extractable text. pypdf splits words on the Legislative Department PDFs
  ("prese nted"). pdfplumber does not, and its `dedupe_chars()` repairs the overprinted
  ("TTTTAAAA") text in some Punjab & Haryana HC PDFs.
- *Dhananjay Rathi v. Ruchika Rathi* (2026 INSC 360) is byte-identical in both the `divorce/`
  and `domestic_violence/` folders.
- Two files under SC `maintainence/` are not about family law: *Balaji Formalin v. UoI*
  (poisons rules) and *Sardari Lal v. Bishan Dass* (a will). The owner chose to keep everything.

## Decision

- Phase 2 ingests **both** the statute (HMA 1955) and the judgments.
- One `Chunk` schema with `kind` ∈ {`section`, `provision`, `judgment_summary`,
  `judgment_paragraph`}, plus a `Document` record per source (`app/ingestion/models.py`).
- Statutes: section parents, plus provision children at the first clause level. Amendment
  footnotes are attached to their section. IDs look like `hma1955:s13:ss1:cl(ia)`.
- Judgments: S.C.R. "Issue for Consideration" / "Headnotes" summary chunks, plus numbered-
  paragraph chunks (`<doc_id>:p15`). `doc_id` = `sc-`/`hc-` + the first 10 hex characters of the
  file's sha256, which stays stable however the file is renamed or moved.
- Byte-identical files collapse into one document that carries all of their topics. Off-topic
  files are kept as the owner chose. The topic metadata lets retrieval filter them later.
- Metadata (court, date, citation, bench) is extracted on a best-effort basis. Missing values
  stay `null` and are listed in `ingest_report.json`. Nothing is guessed.
- The PDFs stay git-ignored. `data/manifest.json` (path, sha256, size, topic, extracted
  metadata, origins) is committed and is the reproducible record of the corpus.
- `pdfplumber` goes in the optional `ingest` extra. CI installs it so mypy can check
  `app.ingestion`.

## Consequences

- Retrieval (Phase 3+) gets statute text and case law from a single chunk store, and can filter
  by `kind`, `court_level`, `topics` and `statutes_cited`.
- The gold queries in `data/evaluation/gold_queries.jsonl` reference chunk IDs, so any ID
  change must be applied to them too. An integration test checks that every ID still exists.
- Adding another Act means adding an `ActSpec` plus its PDF path in `pipeline.STATUTES`.

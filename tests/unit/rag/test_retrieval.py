from pathlib import Path

import pytest

from app.retrieval.corpus import Corpus, CorpusNotFoundError
from app.retrieval.index import IndexMeta, IndexNotReadyError, Retriever, build_index
from app.retrieval.store import point_id
from tests.fakes import FakeEmbedder, make_corpus, make_store


def test_retrieval_units_exclude_parents_but_keep_childless_sections() -> None:
    ids = [c.chunk_id for c in make_corpus().retrieval_units()]

    assert "act1:s2" not in ids  # has provisions → context only
    assert set(ids) == {"act1:s2:ss1", "act1:s2:ss2", "act1:s3", "sc-test:issue", "sc-test:p4"}


def test_parent_lookup() -> None:
    corpus = make_corpus()

    parent = corpus.parent(corpus.chunks["act1:s2:ss1"])
    assert parent is not None
    assert parent.chunk_id == "act1:s2"
    assert corpus.parent(corpus.chunks["sc-test:p4"]) is None


def test_fingerprint_changes_with_text() -> None:
    corpus = make_corpus()
    edited = make_corpus()
    edited.chunks["sc-test:p4"].text = "4. Changed."

    assert corpus.fingerprint() == make_corpus().fingerprint()
    assert corpus.fingerprint() != edited.fingerprint()


def test_load_round_trip_and_missing_files(tmp_path: Path) -> None:
    corpus = make_corpus()
    (tmp_path / "documents.jsonl").write_text(
        "\n".join(d.model_dump_json() for d in corpus.documents.values()), encoding="utf-8"
    )
    (tmp_path / "chunks.jsonl").write_text(
        "\n".join(c.model_dump_json() for c in corpus.chunks.values()) + "\n\n", encoding="utf-8"
    )

    loaded = Corpus.load(tmp_path)
    assert list(loaded.chunks) == list(corpus.chunks)
    assert loaded.fingerprint() == corpus.fingerprint()
    with pytest.raises(CorpusNotFoundError):
        Corpus.load(tmp_path / "missing")


def test_point_ids_are_stable_uuids() -> None:
    assert point_id("act1:s2:ss1") == point_id("act1:s2:ss1")
    assert point_id("act1:s2:ss1") != point_id("act1:s2:ss2")


def test_build_index_then_search(tmp_path: Path) -> None:
    corpus, embedder, store = make_corpus(), FakeEmbedder(), make_store()
    progress: list[tuple[int, int]] = []

    meta = build_index(
        corpus,
        embedder,
        store,
        tmp_path,
        batch_size=2,
        on_progress=lambda done, total: progress.append((done, total)),
    )

    assert meta.chunk_count == 5 == store.count()
    assert progress[-1] == (5, 5)
    assert IndexMeta.read(tmp_path) == meta
    hits = Retriever(corpus, embedder, store).search("which delta custody", top_k=2)
    assert [h.rank for h in hits] == [1, 2]
    assert hits[0].chunk.doc_id == "sc-test"
    assert hits[0].score >= hits[1].score


def test_rebuild_replaces_collection(tmp_path: Path) -> None:
    corpus, embedder, store = make_corpus(), FakeEmbedder(), make_store()
    build_index(corpus, embedder, store, tmp_path)
    build_index(corpus, embedder, store, tmp_path)

    assert store.count() == 5


def test_check_ready_rejects_missing_mismatched_or_stale_index(tmp_path: Path) -> None:
    corpus, embedder = make_corpus(), FakeEmbedder()
    with pytest.raises(IndexNotReadyError, match="No index"):
        Retriever.check_ready(corpus, embedder, tmp_path)

    build_index(corpus, embedder, make_store(), tmp_path)
    assert Retriever.check_ready(corpus, embedder, tmp_path).chunk_count == 5

    with pytest.raises(IndexNotReadyError, match="built with"):
        Retriever.check_ready(corpus, FakeEmbedder(model_name="other"), tmp_path)

    stale = make_corpus()
    stale.chunks["act1:s3"].text = "3. Edited."
    with pytest.raises(IndexNotReadyError, match="Corpus changed"):
        Retriever.check_ready(stale, embedder, tmp_path)

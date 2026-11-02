"""Wire the RAG service from settings (the only place concrete providers are chosen)."""

import os

from qdrant_client import QdrantClient

from app.agents.orchestrator import Orchestrator
from app.core.config import Settings
from app.providers.asr import FasterWhisperASR
from app.providers.embedding import SentenceTransformerEmbedder
from app.providers.gemini import GeminiLLM
from app.providers.llm import LLMProvider, OllamaLLM
from app.providers.reranker import CrossEncoderReranker
from app.providers.translation import LLMTranslator
from app.providers.tts import MMSTTS
from app.retrieval.corpus import Corpus
from app.retrieval.index import Retriever
from app.retrieval.store import VectorStore


def build_embedder(settings: Settings) -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(
        settings.embedding_model,
        cache_dir=settings.models_dir / "hf",
        device=settings.embedding_device,
    )


def build_reranker(settings: Settings) -> CrossEncoderReranker | None:
    if not settings.rerank_enabled:
        return None
    return CrossEncoderReranker(
        settings.reranker_model,
        cache_dir=settings.models_dir / "hf",
        device=settings.reranker_device,
    )


def build_retriever(
    settings: Settings, corpus: Corpus, embedder: SentenceTransformerEmbedder, store: VectorStore
) -> Retriever:
    return Retriever(
        corpus,
        embedder,
        store,
        mode=settings.retrieval_mode,
        reranker=build_reranker(settings),
        candidate_k=settings.retrieval_candidates,
        rerank_strategy=settings.rerank_strategy,
    )


def build_vector_store(settings: Settings) -> VectorStore:
    if settings.qdrant_url:
        return VectorStore(QdrantClient(url=settings.qdrant_url))
    path = settings.index_dir / "qdrant"
    path.mkdir(parents=True, exist_ok=True)
    return VectorStore(QdrantClient(path=str(path)))


def build_llm(settings: Settings, *, light: bool = False) -> LLMProvider:
    """The configured LLM. ``light`` = the model for short calls (Gemini only; else the same)."""
    if settings.llm_provider == "gemini":
        if settings.gemini_api_key is None:  # Settings validation already enforces this
            raise ValueError("LEGALAI_GEMINI_API_KEY is not set")
        model = (settings.gemini_light_model if light else None) or settings.gemini_model
        return GeminiLLM(
            settings.gemini_api_key.get_secret_value(),
            model,
            base_url=settings.gemini_base_url,
            temperature=settings.llm_temperature,
            timeout_s=settings.gemini_timeout_s,
            thinking_level=settings.gemini_thinking_level,
            max_retry_wait_s=settings.gemini_max_retry_wait_s,
        )
    return OllamaLLM(
        settings.ollama_base_url,
        settings.ollama_model,
        temperature=settings.llm_temperature,
        num_ctx=settings.llm_num_ctx,
        timeout_s=settings.llm_timeout_s,
        keep_alive=settings.llm_keep_alive,
    )


def build_orchestrator(settings: Settings) -> Orchestrator:
    """Load the corpus, verify the index matches it, and connect the providers.

    Raises ``CorpusNotFoundError`` / ``IndexNotReadyError`` when setup steps are missing.
    """
    corpus = Corpus.load(settings.data_dir / "processed")
    embedder = build_embedder(settings)
    Retriever.check_ready(corpus, embedder, settings.index_dir)
    store = build_vector_store(settings)
    retriever = build_retriever(settings, corpus, embedder, store)
    llm = build_llm(settings)
    light = build_llm(settings, light=True) if settings.gemini_light_model else llm
    return Orchestrator(
        retriever,
        llm,
        LLMTranslator(llm, light_llm=light),
        light_llm=light,
        # A local model is loaded by a ping; a remote API would only spend daily quota.
        warmup_llm=settings.llm_provider == "ollama",
        top_k=settings.retrieval_top_k,
        max_rounds=settings.agent_max_rounds,
        assess_evidence=settings.agent_assess_evidence,
        max_sources=settings.agent_max_sources,
    )


def build_asr(settings: Settings) -> FasterWhisperASR:
    """Cheap: the model loads on first use (or in the startup warm-up)."""
    return FasterWhisperASR(
        settings.asr_model,
        settings.models_dir / "whisper",
        device=settings.asr_device,
        compute_type=settings.asr_compute_type,
        cpu_threads=settings.asr_cpu_threads or (os.cpu_count() or 4),
        beam_size=settings.asr_beam_size,
        max_seconds=settings.asr_max_seconds,
    )


def build_tts(settings: Settings) -> MMSTTS:
    """Cheap: voices load on first use per language (or in the startup warm-up)."""
    return MMSTTS(settings.models_dir / "hf", cpu_threads=settings.tts_cpu_threads)

"""Skill retrieval backends — pluggable ranking for evolved-skill injection.

``SkillRetriever`` is the abstract contract: given a task query and a set of
candidate skills (name/description/prompt), return them ranked by relevance.
``TfIdfSkillRetriever`` is the zero-dependency default (lexical cosine
similarity).  ``EmbeddingSkillRetriever`` is the reserved plug-in point for a
future vector backend — it documents the contract without pulling in any
embedding dependency, so the default stays dependency-free.

Selection is centralized in ``get_retriever()`` so AgentLoop and R4Agent never
bind to a concrete backend.
"""

from __future__ import annotations

import math
import threading
from abc import ABC, abstractmethod
from collections import Counter

from l1.kernel.params.agent import (
    R4_RETRIEVAL_BACKEND_DEFAULT,
    R4_RETRIEVAL_CACHE_MAX,
    R4_RETRIEVAL_MIN_SCORE,
    R4_RETRIEVAL_PRIORITY_WEIGHT,
)


class SkillRetriever(ABC):
    """Abstract skill retriever — rank candidate skills by query relevance."""

    @abstractmethod
    def rank(
        self, query: str, candidates: list[dict], limit: int, min_score: float = R4_RETRIEVAL_MIN_SCORE
    ) -> list[dict]:
        """Return up to ``limit`` candidates ranked by relevance.

        Candidates are dicts with at least ``name``/``description``/``prompt``.
        Candidates scoring below ``min_score`` (or an empty result set) are
        dropped so the caller can fall back to deterministic ordering.
        """


class TfIdfSkillRetriever(SkillRetriever):
    """Lexical tf-idf retriever — zero new dependencies.

    Tokenizes the query and each candidate's description+prompt, scores by
    cosine similarity of token-frequency vectors, and returns the top-K.

    Candidate token vectors are cached by their full text (description +
    prompt) with an LRU-style cap, so repeated retrievals over the same
    skill corpus skip re-tokenization entirely. The cache key is the text
    itself: a skill revision that changes description/prompt produces a new
    key, so stale vectors can never be served (content-addressed, no manual
    invalidation).
    """

    def __init__(self) -> None:
        self._vector_cache: dict[str, Counter] = {}
        self._cache_lock = threading.Lock()

    def rank(
        self, query: str, candidates: list[dict], limit: int, min_score: float = R4_RETRIEVAL_MIN_SCORE
    ) -> list[dict]:
        """Rank candidates by tf-idf cosine similarity; returns top ``limit``."""
        q_tok = self._tokens(query)
        if not q_tok or not candidates:
            return []
        scored: list[tuple[float, dict]] = []
        for cand in candidates:
            text = f"{cand.get('description', '')} {cand.get('prompt', '')}"
            s_tok = self._cached_tokens(text)
            if not s_tok:
                continue
            common = sum((q_tok & s_tok).values())
            if common == 0:
                continue
            q_norm = math.sqrt(sum(v * v for v in q_tok.values()))
            s_norm = math.sqrt(sum(v * v for v in s_tok.values()))
            if q_norm == 0 or s_norm == 0:
                continue
            base = common / (q_norm * s_norm)
            # Priority weighting: a custom skill's declared priority (0..N)
            # adds a bounded boost to the relevance score so higher-priority
            # skills surface first on equal relevance. The boost is capped so
            # it can never outrank a genuinely more relevant skill.
            priority = int(cand.get("priority", 0) or 0)
            boost = min(R4_RETRIEVAL_PRIORITY_WEIGHT * max(priority, 0), R4_RETRIEVAL_PRIORITY_WEIGHT)
            scored.append((base + boost, cand))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored or scored[0][0] < min_score:
            return []
        return [cand for _, cand in scored[:limit]]

    def _cached_tokens(self, text: str) -> Counter:
        """Return the token vector for *text*, computing and caching on miss.

        Content-addressed: the text is the cache key, so any change to the
        candidate (description/prompt) yields a miss and a fresh vector —
        no explicit invalidation is needed. Bounded by
        ``R4_RETRIEVAL_CACHE_MAX`` with oldest-first eviction.
        """
        if not text:
            return Counter()
        with self._cache_lock:
            cached = self._vector_cache.get(text)
            if cached is not None:
                return cached
        vec = self._tokens(text)
        with self._cache_lock:
            if text not in self._vector_cache:
                if len(self._vector_cache) >= R4_RETRIEVAL_CACHE_MAX:
                    self._vector_cache.pop(next(iter(self._vector_cache)))
                self._vector_cache[text] = vec
        return vec

    @staticmethod
    def _tokens(text: str) -> Counter:
        return Counter(w.lower() for w in text.split() if len(w) > 2)


class EmbeddingSkillRetriever(SkillRetriever):
    """Vector-backend retriever — embeds query + candidates, ranks by cosine.

    Uses ``LLMEngine.embed`` (the active provider's embedding endpoint,
    e.g. Ollama ``/api/embed`` or an OpenAI-compatible ``/embeddings``).
    When the provider does not support embeddings, the network fails, or no
    candidate clears the similarity floor, ``rank`` returns ``[]`` so the
    caller (``retrieve_skills``) falls back to deterministic ordering —
    degradation, never failure.
    """

    def rank(
        self, query: str, candidates: list[dict], limit: int, min_score: float = R4_RETRIEVAL_MIN_SCORE
    ) -> list[dict]:
        """Rank candidates by embedding cosine similarity; returns top ``limit``."""
        if not query or not candidates:
            return []
        texts = [query] + [f"{c.get('description', '')} {c.get('prompt', '')}" for c in candidates]
        try:
            from l4.llm.llm import get_engine

            r = get_engine().embed(texts)
        except Exception:
            return []
        if not r.get("success"):
            return []
        vectors = r.get("vectors") or []
        if len(vectors) != len(texts):
            return []
        q_vec = vectors[0]
        scored: list[tuple[float, dict]] = []
        for cand, vec in zip(candidates, vectors[1:], strict=False):
            sim = _cosine(q_vec, vec)
            if sim >= min_score:
                scored.append((sim, cand))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [cand for _, cand in scored[:limit]]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors (pure Python)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── Backend selection ──
_RETRIEVERS: dict[str, type[SkillRetriever]] = {
    "tfidf": TfIdfSkillRetriever,
    "embedding": EmbeddingSkillRetriever,
}

_retriever: SkillRetriever | None = None
_backend_name: str = "tfidf"


def get_retriever(name: str = "") -> SkillRetriever:
    """Return the shared retriever instance for a backend name.

    With an empty ``name`` (the common case): if an instance already exists
    (set by ``set_backend`` at runtime), it is returned as-is — a runtime
    switch must survive subsequent calls.  Only when no instance exists yet
    (first use, or after restart) is the initial backend read from config
    ``skill.retriever_backend`` (falling back to
    ``R4_RETRIEVAL_BACKEND_DEFAULT``).  An explicit non-empty ``name``
    overrides config.  Unknown names fall back to tfidf so a misconfigured
    selector never breaks injection (degradation, not failure).
    """
    global _retriever, _backend_name
    if name:
        cls = _RETRIEVERS.get(name, TfIdfSkillRetriever)
        if _retriever is None or not isinstance(_retriever, cls):
            _retriever = cls()
            _backend_name = "tfidf" if cls is TfIdfSkillRetriever else name
        return _retriever
    if _retriever is None:
        effective = _config_backend()
        cls = _RETRIEVERS.get(effective, TfIdfSkillRetriever)
        _retriever = cls()
        _backend_name = "tfidf" if cls is TfIdfSkillRetriever else effective
    return _retriever


def _config_backend() -> str:
    """Resolve the configured initial backend (config → params default)."""
    default = R4_RETRIEVAL_BACKEND_DEFAULT
    try:
        from l3.config.settings_center import get_center

        backend = str(get_center().get("skill.retriever_backend", default))
        return backend if backend in _RETRIEVERS else default
    except Exception:
        return default


def set_backend(name: str) -> dict:
    """Switch the active retriever backend at runtime.

    ``name`` must be one of ``available_backends()``; an unknown name is
    rejected (does not silently fall back) so a typo in API/L2 control is
    visible.  Returns the effective backend + available list.
    """
    global _retriever, _backend_name
    if name not in _RETRIEVERS:
        return {"success": False, "error": f"unknown retriever backend '{name}'", "available": available_backends()}
    cls = _RETRIEVERS[name]
    _retriever = cls()
    _backend_name = name
    return {"success": True, "backend": name, "available": available_backends()}


def retriever_status() -> dict:
    """Return the active retriever backend and the available backends."""
    get_retriever()  # ensure an instance exists
    return {"backend": _backend_name, "available": available_backends()}


def reset_retriever() -> None:
    """Drop the shared retriever instance (test isolation)."""
    global _retriever
    _retriever = None


def available_backends() -> list[str]:
    """List registered retriever backend names (for config/observability)."""
    return sorted(_RETRIEVERS)

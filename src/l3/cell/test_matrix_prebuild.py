"""Test-matrix prebuild — asynchronous parallel test-matrix precompute.

Phase 3.1 of the organizational-evolution design (see
``docs/design/related-work.md``): when department division is active
(``departments.enabled`` + ``departments.test_matrix_prebuild`` both on, and
the Cell count reaches ``CELL_DEPARTMENT_MIN``), the testing department's
matrices are prebuilt in the background (bounded ``ThreadPoolWorker``) and
cached in the tiered-cache L2 cross-cell layer. A tester AgentLoop then reads
a ready matrix instead of building it synchronously.

Bounded + degrading (never raises):
  - per-card rows capped by ``TEST_MATRIX_PREBUILD_MAX``
  - background pool capped by ``TEST_MATRIX_PARALLEL_WORKERS``
  - cache TTL ``TEST_MATRIX_TTL`` (tiered-cache L2 expiry)
  - cache miss / prebuild off / any failure -> synchronous rule-based build
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.agent import (
    TEST_MATRIX_PARALLEL_WORKERS,
    TEST_MATRIX_PREBUILD_MAX,
)
from l1.kernel.params.system import LOG_TRUNC_60, LOG_TRUNC_200

logger = logging.getLogger(__name__)

# tiered-cache L2 key suffix for prebuilt matrices (cell::card::test_matrix).
_MATRIX_KEY_SUFFIX = "test_matrix"

_pool: Any = None
_pool_lock = threading.Lock()


def prebuild_enabled() -> bool:
    """Return whether background prebuild is active (settings + threshold).

    Both settings flat keys default false; the Cell-count threshold comes
    from the department manager's ``active()`` (switch AND count). Any
    failure degrades to False — prebuild is an optimization, never a gate.

    Returns:
        True when both switches are on and division is active.
    """
    try:
        from l1.kernel.settings import get_settings
        from l3.cell.department import get_department_manager

        if not bool(get_settings().get("departments.test_matrix_prebuild", False)):
            return False
        return bool(get_department_manager().active())
    except Exception as e:
        logger.debug("test_matrix_prebuild: enabled check skipped: %s", e)
        return False


def build_matrix(card_id: str, intent: str = "", domain: str = "") -> list[dict]:
    """Build a bounded test matrix for one card (rule-based, no LLM).

    The matrix is a structured list of test rows (positive / negative /
    boundary facets) with the card's intent and domain attached for the
    testing department's context. Generic facets are the built-in minimal
    generalization — a deployment may override the row shape via a custom
    builder later, never by editing this function's data.

    Args:
        card_id: the driving card id (matrix key component).
        intent: card title / intent text (truncated into the row).
        domain: optional card domain hint.

    Returns:
        List of matrix rows; length is bounded by TEST_MATRIX_PREBUILD_MAX.
    """
    facets = (
        {"case": "positive", "expect": "core behavior holds under valid input"},
        {"case": "negative", "expect": "invalid input is rejected"},
        {"case": "boundary", "expect": "edge values are handled"},
    )
    rows: list[dict] = []
    for entry, facet in enumerate(facets[:TEST_MATRIX_PREBUILD_MAX]):
        rows.append(
            {
                "card_id": card_id,
                "intent": (intent or "")[:LOG_TRUNC_60],
                "domain": (domain or "")[:LOG_TRUNC_60],
                "case": facet["case"],
                "expect": facet["expect"][:LOG_TRUNC_200],
                "entry": entry,
            }
        )
    return rows


def _matrix_key(cell_id: str, card_id: str) -> str:
    """Build the tiered-cache L2 key for one card's prebuilt matrix."""
    return f"{cell_id}::{card_id}::{_MATRIX_KEY_SUFFIX}"


def _ensure_pool() -> Any:
    """Lazily create the bounded background worker pool (never shared)."""
    global _pool
    with _pool_lock:
        if _pool is None:
            from l1.kernel.worker_thread import ThreadPoolWorker

            _pool = ThreadPoolWorker(
                min_workers=1,
                max_workers=TEST_MATRIX_PARALLEL_WORKERS,
                queue_size=64,
            )
        return _pool


def schedule_prebuild(cell_id: str, card_id: str, intent: str = "", domain: str = "") -> bool:
    """Submit an asynchronous matrix prebuild for one card (non-blocking).

    Fire-and-forget: returns immediately; a full queue drops the oldest
    pending task (worker-pool FIFO eviction). When prebuild is off or the
    submit fails, returns False — the consumer falls back to a synchronous
    build on read.

    Returns:
        True when the task was submitted, False when prebuild is inactive
        or the submit failed.
    """
    if not prebuild_enabled():
        return False
    try:
        _ensure_pool().submit(_prebuild_one, cell_id, card_id, intent, domain)
        return True
    except Exception as e:
        logger.debug("test_matrix_prebuild: schedule skipped: %s", e)
        return False


def _prebuild_one(cell_id: str, card_id: str, intent: str, domain: str) -> None:
    """Build one matrix and cache it in the tiered-cache L2 layer."""
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        matrix = build_matrix(card_id, intent, domain)
        get_tiered_cache().set_shared_summary(cell_id, _matrix_key(cell_id, card_id), matrix)
    except Exception as e:
        logger.debug("test_matrix_prebuild: prebuild skipped: %s", e)


def get_matrix(cell_id: str, card_id: str, intent: str = "", domain: str = "") -> list[dict]:
    """Return the prebuilt matrix for a card, or build it synchronously.

    Cache hit returns the stored rows; a miss, an inactive prebuild, or any
    failure falls back to the same bounded rule-based build — the tester
    always receives a matrix, never an error.

    Returns:
        List of matrix rows (prebuilt or freshly built).
    """
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        cached = get_tiered_cache().get_shared_summary(cell_id, _matrix_key(cell_id, card_id))
        if isinstance(cached, list) and cached:
            return cached
    except Exception as e:
        logger.debug("test_matrix_prebuild: cache read skipped: %s", e)
    return build_matrix(card_id, intent, domain)


def reset_test_matrix_prebuild() -> None:
    """Shut down the background pool (tests / lifecycle)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.shutdown(wait=False)
            except Exception as e:
                logger.debug("test_matrix_prebuild: pool shutdown skipped: %s", e)
            _pool = None

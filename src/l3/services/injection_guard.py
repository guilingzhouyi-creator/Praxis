"""InjectionGuard — rule-based prompt-injection detection for PreConnect.

Owns the injection pattern table, risk scoring, threshold adjudication and
the optional external LLM reviewer callback, so the L2 selector only calls
injection_verify()/injection_scan() through the L2→L3 bridge. Patterns are
data-first: the ZH patterns and thresholds come from kernel params.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from l1.kernel.params.agent import (
    INJECTION_HIGH_RISK_THRESHOLD,
    INJECTION_LENGTH_BOOST,
    INJECTION_LENGTH_THRESHOLD,
    INJECTION_MEDIUM_RISK_THRESHOLD,
    INJECTION_PATTERN_ZH1,
    INJECTION_PATTERN_ZH2,
    INJECTION_REVIEW_BOOST,
    INJECTION_REVIEW_REWARD,
)
from l3.error_bus import capture

logger = logging.getLogger(__name__)

# Known injection patterns (rule-based, expand over time).
_INJECTION_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"ignore\s+(all\s+)?(previous|above|system)\s+(instructions|prompts)", re.I), 0.5),
    (re.compile(r"forget\s+(all\s+)?(previous|above|system)", re.I), 0.5),
    (re.compile(INJECTION_PATTERN_ZH1, re.I), 0.5),
    (re.compile(r"disregard\s+(all\s+)?(previous|above)", re.I), 0.4),
    (re.compile(INJECTION_PATTERN_ZH2, re.I), 0.4),
    (re.compile(r"new\s+instructions?:?\s*$", re.I), 0.3),
    (re.compile(r"system\s+(prompt|message):", re.I), 0.2),
    (re.compile(r"<\s*system\s*>", re.I), 0.2),
    (re.compile(r"role\s*:\s*system", re.I), 0.2),
]

# External LLM reviewer callback (hook-injected, never imported).
_llm_reviewer: Any = None
_llm_reviewer_lock = threading.Lock()


def set_llm_reviewer(callback: Any) -> None:
    """Register an external LLM reviewer for prompt injection.

    The callback receives (message: str) and should return
    {"safe": bool, "reason": str, "confidence": float}.
    Called by injection_verify() when the rule-based score is inconclusive.
    """
    with _llm_reviewer_lock:
        global _llm_reviewer
        _llm_reviewer = callback
    logger.info("llm_reviewer registered")


def reset_injection_guard() -> None:
    """Reset module state (test/restart helper): drop the reviewer callback."""
    with _llm_reviewer_lock:
        global _llm_reviewer
        _llm_reviewer = None


def injection_scan(message: str) -> float:
    """Scan a message for injection patterns; returns risk score 0.0-1.0."""
    if not message:
        return 0.0
    score = 0.0
    for pattern, weight in _INJECTION_PATTERNS:
        if pattern.search(message):
            score += weight
    # Length heuristic: very long messages with injection-like patterns.
    if len(message) > INJECTION_LENGTH_THRESHOLD and score > 0:
        score = min(1.0, score + INJECTION_LENGTH_BOOST)
    return min(1.0, score)


def injection_verify(message: str) -> dict:
    """Adjudicate one message: allowed / injection_risk / reason.

    High risk → deny; medium risk → ask the LLM reviewer (if registered);
    low risk → allow.
    """
    if not message:
        return {"allowed": True, "injection_risk": 0.0, "reason": "ok"}
    score = injection_scan(message)
    if score > INJECTION_HIGH_RISK_THRESHOLD:
        return {"allowed": False, "injection_risk": score, "reason": "prompt_injection_suspected"}
    if score > INJECTION_MEDIUM_RISK_THRESHOLD:
        with _llm_reviewer_lock:
            reviewer = _llm_reviewer
        if reviewer:
            try:
                review = reviewer(message)
                if not review.get("safe", False):
                    return {
                        "allowed": False,
                        "injection_risk": min(1.0, score + INJECTION_REVIEW_BOOST),
                        "reason": f"llm_review: {review.get('reason', 'unsafe')}",
                    }
                return {
                    "allowed": True,
                    "injection_risk": max(0.0, score - INJECTION_REVIEW_REWARD),
                    "reason": "ok",
                }
            except Exception as e:
                logger.warning("llm_review failed: %s", e)
                capture("llm_review failed", error_code="E_LLM_REVIEW", component="l3")
        return {"allowed": True, "injection_risk": score, "reason": "ok"}
    return {"allowed": True, "injection_risk": score, "reason": "ok"}

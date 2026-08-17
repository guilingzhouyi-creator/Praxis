"""Identity UID issuer — system-issued declarative identity registry keys.

Phase A of the identity-constrained system (see ``docs/design/
related-work.md``): every identity binding carries a system-issued UID so
department registration can reference identities by id (declarative
dependency registration). The UID is issued by this L1 singleton — never
client-supplied — with a readable prefix and a bounded body length
(``IDENTITY_UID_PREFIX`` / ``IDENTITY_UID_LENGTH``).

The issuer keeps a seen-set of live UIDs so duplicates cannot be handed
out; a lost registry resets the seen-set (issuance is idempotent across
restarts because bindings persist their UID, they never re-request one).

Degrades gracefully: an import/issuance failure returns "" so callers fall
back to no-UID behavior instead of raising.
"""

from __future__ import annotations

import logging
import secrets
import threading

from .params.agent import IDENTITY_UID_LENGTH, IDENTITY_UID_PREFIX

logger = logging.getLogger(__name__)

_seen: set[str] = set()
_lock = threading.RLock()


def issue_identity_uid() -> str:
    """Issue a fresh, unique identity UID (readable prefix + random body).

    Returns:
        A new UID string, or "" when issuance fails (graceful no-op).
    """
    global _seen
    try:
        for _ in range(8):  # bounded retries for collision-resilience
            body = secrets.token_hex(IDENTITY_UID_LENGTH // 2)[:IDENTITY_UID_LENGTH]
            uid = f"{IDENTITY_UID_PREFIX}{body}"
            with _lock:
                if uid not in _seen:
                    _seen.add(uid)
                    return uid
    except Exception as e:
        logger.warning("identity_uid: issuance failed: %s", e)
    return ""


def verify_identity_uid(uid: str) -> bool:
    """Return whether *uid* is well-formed (prefix + length). Never raises."""
    if not isinstance(uid, str) or not uid:
        return False
    body = uid[len(IDENTITY_UID_PREFIX) :]
    return uid.startswith(IDENTITY_UID_PREFIX) and len(body) == IDENTITY_UID_LENGTH


def _track_existing(uid: str) -> None:
    """Register an already-persisted UID into the seen-set (restore path)."""
    if uid:
        with _lock:
            _seen.add(uid)


def reset_identity_uid() -> None:
    """Clear the seen-set (tests / lifecycle)."""
    global _seen
    with _lock:
        _seen = set()

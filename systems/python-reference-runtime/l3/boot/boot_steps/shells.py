"""Boot step — shell family instantiation from merged config."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _init_shells() -> dict:
    """Load the shell family from the merged ``shells`` config section.

    Reads the three-layer merged config (params defaults ← discovery
    shells.yaml ← praxis.yaml overrides) and instantiates the declared
    shell dialects into the ShellFamily registry.  A failed family load is
    non-fatal: the system still boots with an empty family.
    """
    from l1.kernel.discovery import get_config
    from l2.shells.family import get_family, reset_family

    reset_family()
    family = get_family()
    cfg = get_config("shells") or {}
    try:
        count = family.load_config(cfg)
        logger.info("boot: shell family loaded (%d shell(s), default=%s)", count, family.snapshot()["default"])
        return {"success": True, "shells": count}
    except Exception as e:
        logger.warning("boot: shell family load failed: %s", e)
        return {"success": True, "_non_fatal": True, "shells": 0, "note": str(e)}

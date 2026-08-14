"""Boot step — runtime directory layout preparation.

``_prepare_layout`` creates every runtime directory that PraxisPaths defines
(``layout_dirs``) before any service writes to them. Historically each
service lazily ``mkdir``ed its own dirs; this step makes the layout explicit,
idempotent and platform-correct (temp dir resolved via ``tempfile``, data
dirs under the platform user-data root).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _prepare_layout() -> dict:
    """Ensure all runtime directories exist (idempotent).

    Creates exactly the directories enumerated in
    ``PraxisPaths.layout_dirs`` (single source of truth — see paths.py), so
    a first install on a fresh machine, a reset, or a deleted data dir are
    all rebuilt on the next boot. Never fails: uncreatable dirs are logged
    and reported, but do not block boot.
    """
    from l1.kernel.paths import get_paths

    paths = get_paths()
    created: list[str] = []
    errors: dict[str, str] = {}
    for d in paths.layout_dirs:
        if not d:
            continue
        try:
            os.makedirs(d, exist_ok=True)
            created.append(d)
        except OSError as e:
            errors[d] = str(e)
            logger.warning("prepare_layout: cannot create %s: %s", d, e)
    logger.info("prepare_layout: %d dirs ready (errors: %d)", len(created), len(errors))
    return {"success": not errors, "created": created, "errors": errors}

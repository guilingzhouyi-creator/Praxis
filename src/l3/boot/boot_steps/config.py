"""Boot step — praxis.yaml config load and apply.

Extracted from ``boot_steps.py``.  ``_load_config`` delegates to the L3
config loader; config-not-found is non-fatal on first boot.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    """Load praxis.yaml config and apply to system settings.

    Returns success=True even on config-not-found so first-boot is not blocked,
    but adds ``_non_fatal`` flag so boot reporting can distinguish."""
    # Dependency inversion: inject the authoritative settings accessor into
    # the kernel layer — kernel never imports L3; the provider is injected.
    try:
        from l1.kernel.settings import set_settings_provider
        from l3.config.settings_adapter import get_settings as _sg
        from l3.config.settings_adapter import reset_settings as _sr

        set_settings_provider(_sg, _sr)
    except Exception as e:
        logger.warning("boot: settings provider inject skipped: %s", e)
    try:
        from l3.config.config_loader import load_and_apply, watch_config

        r = load_and_apply()
        if r.get("success"):
            # Hot-reload: watch praxis.yaml for changes and re-apply settings
            # automatically (non-blocking daemon thread).
            try:
                watch_config()
            except Exception as e:
                logger.warning("config watch start skipped: %s", e)
            return {"success": True, "applied": r.get("applied", {})}
        return {"success": True, "_non_fatal": True, "note": r.get("error", "config load failed")}
    except Exception as e:
        logger.error("config load error: %s", e)
        return {"success": True, "_non_fatal": True, "note": str(e)}

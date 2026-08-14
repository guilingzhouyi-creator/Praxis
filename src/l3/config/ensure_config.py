"""ensure_config — template-driven default configuration provisioning.

First-install (or self-healing after a deleted config) copies the shipped
config templates from ``PraxisPaths.config_templates_dir`` into the active
config location. An existing file is never overwritten — the user's config
is authoritative; only missing files are provisioned.

Template source precedence:
  CLI_PROJECT → repo ``config/``
  installed modes → wheel ``share/praxis/config`` data-files payload
"""

from __future__ import annotations

import logging
import os
import shutil

logger = logging.getLogger(__name__)

# Files copied on first provision (relative to the template dir).
_TEMPLATE_FILES: tuple[str, ...] = (
    "praxis.yaml",
    "commands.yaml",
    "tools.yaml",
    ".praxis-rules.md",
)


def _template_dir() -> str:
    """Resolve the shipped config-template directory for the active mode."""
    from l1.kernel.paths import get_paths

    return get_paths().config_templates_dir


def ensure_config(config_path: str = "") -> dict:
    """Provision the default config when the target file is missing.

    Copies the shipped templates (praxis.yaml, commands.yaml, tools.yaml,
    .praxis-rules.md and config/discovery/*.yaml) from the template dir into
    the target config location. Existing files are never overwritten.

    Args:
        config_path: Explicit target; empty means the active config file
            from PraxisPaths (``get_paths().config_file``).

    Returns:
        {"success": bool, "path": str, "provisioned": [relative names],
         "skipped": [relative names], "error": str?}
    """
    from l1.kernel.paths import get_paths

    paths = get_paths()
    target = config_path or paths.config_file
    tpl = _template_dir()
    if not os.path.isdir(tpl):
        return {"success": False, "path": target, "error": f"template dir not found: {tpl}"}

    target_dir = os.path.dirname(target) or "."
    os.makedirs(target_dir, exist_ok=True)

    provisioned: list[str] = []
    skipped: list[str] = []
    for rel in _TEMPLATE_FILES:
        src = os.path.join(tpl, rel)
        if not os.path.isfile(src):
            continue  # template absent (e.g. subset payload) — skip silently
        dst = os.path.join(target_dir, rel)
        if os.path.exists(dst):
            skipped.append(rel)
            continue
        try:
            shutil.copy2(src, dst)
            provisioned.append(rel)
        except OSError as e:
            logger.warning("ensure_config: copy %s failed: %s", rel, e)
            return {"success": False, "path": target, "error": str(e)}

    # config/discovery/*.yaml — structural overrides ship with the package.
    disc_src = os.path.join(tpl, "discovery")
    disc_dst = os.path.join(target_dir, "discovery")
    if os.path.isdir(disc_src):
        os.makedirs(disc_dst, exist_ok=True)
        for name in sorted(os.listdir(disc_src)):
            if not name.endswith(".yaml"):
                continue
            dst = os.path.join(disc_dst, name)
            if os.path.exists(dst):
                skipped.append(f"discovery/{name}")
                continue
            try:
                shutil.copy2(os.path.join(disc_src, name), dst)
                provisioned.append(f"discovery/{name}")
            except OSError as e:
                logger.warning("ensure_config: discovery copy %s failed: %s", name, e)

    logger.info("ensure_config: %s — provisioned=%s skipped=%s", target, provisioned, skipped)
    return {"success": True, "path": target, "provisioned": provisioned, "skipped": skipped}


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge ``overlay`` into ``base`` (base keys win on leaf).

    Used for upgrade template merges: the user's existing config is ``base``
    (its values are authoritative), the new template is ``overlay`` — keys the
    user already set are preserved, keys added by the new version are filled
    with the template default.
    """
    for key, value in overlay.items():
        if key not in base:
            base[key] = value
        elif isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
    return base


def merge_config_templates(config_path: str = "") -> dict:
    """Merge new-template defaults into an existing user config (upgrade).

    Reads the shipped ``praxis.yaml`` template and deep-merges it under the
    user's current config: user-set keys keep their values, keys introduced
    by the new version take the template default. The pre-merge user config
    is backed up as ``<path>.bak`` (bootstrap convention). Also provisions
    any missing discovery/*.yaml increments. No-op when no template exists.

    Returns:
        {"success": bool, "path": str, "backup": str, "merged": bool,
         "provisioned": [names]}
    """
    import yaml

    from l1.kernel.paths import get_paths

    paths = get_paths()
    target = config_path or paths.config_file
    tpl = os.path.join(paths.config_templates_dir, "praxis.yaml")
    if not os.path.isfile(tpl) or not os.path.isfile(target):
        # Nothing to merge against (fresh install or template-less deploy).
        return {"success": True, "path": target, "backup": "", "merged": False, "provisioned": []}

    try:
        with open(target, encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        with open(tpl, encoding="utf-8") as f:
            tpl_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("merge_config_templates: read failed: %s", e)
        return {"success": False, "path": target, "error": str(e)}

    if not isinstance(user_cfg, dict) or not isinstance(tpl_cfg, dict):
        return {"success": True, "path": target, "backup": "", "merged": False, "provisioned": []}

    backup = target + ".bak"
    try:
        shutil.copy2(target, backup)
    except OSError as e:
        logger.warning("merge_config_templates: backup failed: %s", e)
        return {"success": False, "path": target, "error": f"backup failed: {e}"}

    merged = _deep_merge(dict(user_cfg), tpl_cfg)
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(merged, f, default_flow_style=False, sort_keys=False, allow_unicode=True, indent=2)
        os.replace(tmp, target)
    except Exception as e:
        logger.warning("merge_config_templates: write failed: %s", e)
        return {"success": False, "path": target, "error": str(e)}

    # Provision discovery increments added by the new version (no overwrite).
    provisioned = ensure_config(config_path=target).get("provisioned", [])
    logger.info("merge_config_templates: %s merged (backup=%s)", target, backup)
    return {
        "success": True,
        "path": target,
        "backup": backup,
        "merged": True,
        "provisioned": provisioned,
    }

"""SkillPersistMixin — loading + persistence for SkillManager.

Extracted from skill.py.  The mixin owns discovery-dir resolution, the
SKILL.md / YAML loaders, frontmatter normalization and the registry
store; the concrete ``SkillManager`` composes it with the
policy/guidance/retrieval mixins and owns the shared registry state.

The module-level helpers here (``_is_builtin_path``,
``resolve_skill_dirs``, ``_strip_universal_principles`` …) were moved
out of skill.py together with the loaders that use them; skill.py
re-exports them so ``from l1.kernel.skill import …`` keeps working.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from l1.kernel.params.system import (
    LOG_TRUNC_200,
    LOG_TRUNC_2000,
    SKILL_DISCLOSURE_DEFAULT,
    SKILL_DISCLOSURE_VALID,
    SKILL_POSTURE_DEFAULT,
    SKILL_POSTURE_VALID,
    SKILL_SCOPE_VALID,
    SKILL_STATUS_DEFAULT,
    SKILL_STATUS_VALID,
)

logger = logging.getLogger(__name__)

# Directory marker for built-in (read-only) skills shipped with the repo.
_BUILTIN_SKILL_DIR = "config/skills"


def _is_builtin_path(path: str) -> bool:
    """Return True when a skill file lives under the built-in skills dir."""
    return _BUILTIN_SKILL_DIR in path.replace("\\", "/")


def _get_skill_dirs() -> list[str]:
    """Get skill discovery dirs from config, fall back to built-in paths."""
    try:
        from l1.kernel.discovery import get_config

        cfg = get_config("skill_dirs")
        if cfg and isinstance(cfg, list):
            return cfg
    except Exception:
        logger.debug("skill: skill_dirs config lookup failed, using defaults", exc_info=True)
    return [".praxis/skills", "skills", ".skills"]


SKILL_DIRS = _get_skill_dirs()


def resolve_skill_dirs() -> list[str]:
    """Return skill discovery paths via PraxisPaths (deploy-mode aware)."""
    try:
        from .paths import get_paths

        return get_paths().skill_dirs
    except Exception:
        return list(SKILL_DIRS)


_UNIVERSAL_PRINCIPLES_RE = re.compile(r"^## Universal Principles.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def _strip_universal_principles(body: str) -> str:
    """Remove the duplicated universal-principles section from a skill body.

    The 12 governance principles are normalized into
    ``config/skills/_shared/principles.md`` and injected once per skill at
    load; the per-file section is stripped so sources stay slim and edits
    do not drift across 21 files.
    """
    return _UNIVERSAL_PRINCIPLES_RE.sub("", body, count=1)


class SkillPersistMixin:
    """SkillPersistMixin — discovery-dir loading, markdown/frontmatter parse, store."""

    # ── Attributes injected by the concrete SkillManager (see skill.py) ──
    _lock: threading.RLock
    _skills: dict[str, dict]
    _revision: int
    _shared_principles: str
    _normalize_binding: Callable[[dict | None], dict[str, list[str]]]

    def load_dir(self, directory: str) -> int:
        """Load all skill files from a directory tree.

        Supports:
          - SKILL.md files (Markdown with frontmatter)
          - .yaml/.yml skill definitions
        """
        import yaml

        count = 0
        base = os.path.abspath(directory)
        if not os.path.isdir(base):
            return 0
        # Universal principles live once in <base>/_shared/principles.md and
        # are injected into every loaded skill (normalization: no per-file
        # duplication of the 12 governance principles).
        shared_path = os.path.join(base, "_shared", "principles.md")
        if os.path.isfile(shared_path):
            with open(shared_path, encoding="utf-8") as f:
                self._shared_principles = f.read().strip()
        for root, _dirs, files in os.walk(base):
            for fn in files:
                fp = os.path.join(root, fn)
                if fn == "SKILL.md":
                    if self._load_markdown(fp):
                        count += 1
                elif fn.endswith((".yaml", ".yml")):
                    try:
                        with open(fp, encoding="utf-8") as f:
                            data = yaml.safe_load(f)
                        if isinstance(data, dict) and "name" in data:
                            self._store(data, fp)
                            count += 1
                    except Exception as e:
                        logger.warning("kernel/skill: %s", e)
        if count > 0:
            self._revision += 1
        return count

    def load_builtin(self) -> int:
        """Load built-in skills from deploy-mode-aware search paths."""
        count = 0
        dirs = resolve_skill_dirs()
        import l1.kernel as _kernel

        kernel_dir = os.path.dirname(_kernel.__file__)
        for sd in dirs:
            if os.path.isabs(sd):
                # Absolute path — use directly
                count += self.load_dir(sd)
            else:
                # Relative path — try project root, then src/
                # kernel_dir = <root>/src/l1/kernel → project root is 3 levels up.
                for base in [
                    os.path.join(kernel_dir, "..", "..", ".."),  # project root
                    os.path.join(kernel_dir, "..", ".."),  # src/
                ]:
                    path = os.path.join(base, sd)
                    if os.path.isdir(path):
                        count += self.load_dir(path)
                        break
        # Also load evolved skills from data directory
        try:
            from ..paths import get_paths as _gp

            if os.path.isdir(_gp().skill_evolved_dir):
                count += self.load_dir(_gp().skill_evolved_dir)
        except Exception:
            logger.debug("skill: evolved skills load failed")
        return count

    def _load_markdown(self, path: str) -> bool:
        """Parse SKILL.md file with YAML frontmatter."""
        import yaml

        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return False
        # YAML frontmatter between --- ... ---
        import re

        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not m:
            return False
        try:
            meta = yaml.safe_load(m.group(1))
        except Exception:
            return False
        if not isinstance(meta, dict):
            return False
        body = _strip_universal_principles(content[m.end() :])
        if self._shared_principles:
            body = self._shared_principles + "\n\n" + body
        name = meta.get("name", os.path.basename(os.path.dirname(path)))
        desc = meta.get("description")
        scope = meta.get("scope")
        if scope not in SKILL_SCOPE_VALID:
            scope = ""
        scope_identity = str(meta.get("scope-identity", "") or "").strip()
        # Declarative scope maps into the runtime binding (cell_ids/agent_ids)
        # so the existing skill_is_injectable filter applies unchanged.
        binding = self._normalize_binding(meta.get("binding"))
        if scope and scope_identity:
            binding[("cell_ids" if scope == "cell" else "agent_ids")] = sorted(
                {*binding.get("cell_ids" if scope == "cell" else "agent_ids", []), scope_identity}
            )
        data = {
            "name": name,
            "description": (desc or "")[:LOG_TRUNC_200],
            "rules": self._extract_rules(body),
            "procedures": self._extract_procedures(body),
            "knowledge": {"body": body[:LOG_TRUNC_2000]},
            "source": path,
            "builtin": _is_builtin_path(path),
            "allowed_tools": meta.get("allowed_tools"),
            "variables": meta.get("variables"),
            "tags": meta.get("tags") or [],
            "prompt": body.strip(),
            # Posture: productive (default) vs offensive (reverse/attack
            # testing). Invalid values fall back to the safe default so a
            # malformed frontmatter never escalates a skill's posture.
            "posture": self._normalize_posture(meta.get("posture")),
            "disclosure": self._normalize_disclosure(meta.get("disclosure")),
            "binding": binding,
            "status": self._normalize_status(meta.get("status")),
            # Declarative scope/priority (incremental §11.1): scope-identity +
            # scope select the injection target; priority resolves conflicts
            # between custom and builtin/evolved skills (builtins pin 0).
            "scope": scope,
            "scope_identity": scope_identity,
            "priority": int(meta.get("priority", 0)) if str(meta.get("priority", "0")).lstrip("-").isdigit() else 0,
            # Quest-style staged skills: ordered stages, each with
            # id/name/instructions/completion — progressive disclosure reveals
            # only the active stage (see current_stage/advance_stage).
            "stages": [s for s in (meta.get("stages") or []) if isinstance(s, dict)],
            # Forward guidance (quest-style): skills this skill suggests next.
            "next": [n for n in (meta.get("next") or []) if isinstance(n, str)],
            # Matt-Pocock-style invocation model: user-invoked skills
            # (disable-model-invocation: true) are excluded from automatic
            # context injection; they only fire on explicit use.
            "disable_model_invocation": bool(meta.get("disable-model-invocation", False)),
            # Dependency metadata (ADR-0001 style): prerequisite skills plus
            # strength. hard = output is wrong without the dependency; soft =
            # output is just less sharp. Defaults keep legacy skills working.
            "dependencies": list(meta.get("dependencies") or []),
            "dependency_kind": str(meta.get("dependency-kind", "soft")),
            # Field defaults so reloaded skills match programmatic create()
            # (round-trip integrity — tags/useful_count/last_used must survive).
            "useful_count": 0,
            "last_used": 0.0,
            "loaded_at": time.time(),
        }
        # E1: constitutional gate at load time — a skill whose registration
        # violates the constitution (e.g. instructs bypassing sandbox/gates)
        # is rejected before it enters the pool (fail-fast).
        try:
            from l1.kernel.constitution import get_constitution

            cc = get_constitution().is_allowed("skill.load", "system", target=name)
            if not cc.get("allowed"):
                logger.warning("skill: load blocked by constitution: %s", cc.get("blocks"))
                return False
        except Exception as e:
            logger.debug("skill: constitution check skipped at load: %s", e)
        self._store(data, path)
        return True

    @staticmethod
    def _normalize_posture(value: Any) -> str:
        """Normalize a posture value to a valid posture, defaulting to productive.

        Invalid values (or missing) fall back to the safe default so a
        malformed frontmatter or caller can never escalate a skill's posture.
        """
        if isinstance(value, str) and value in SKILL_POSTURE_VALID:
            return value
        return SKILL_POSTURE_DEFAULT

    @staticmethod
    def _normalize_disclosure(value: Any) -> str:
        """Normalize a disclosure value to full|index|none, defaulting to full.

        Invalid values (or missing) fall back to the safe default so a
        malformed frontmatter never hides a skill by accident — full means
        the skill participates in all progressive-disclosure levels.
        """
        if isinstance(value, str) and value in SKILL_DISCLOSURE_VALID:
            return value
        return SKILL_DISCLOSURE_DEFAULT

    @staticmethod
    def _normalize_status(value: Any) -> str:
        """Normalize a persisted lifecycle state to the active default."""
        if isinstance(value, str) and value in SKILL_STATUS_VALID:
            return value
        return SKILL_STATUS_DEFAULT

    def _extract_rules(self, body: str) -> list[str]:
        """Extract DO/DON'T rules from markdown body.

        Accepts both ``- **DO:** ...`` and ``- DO: ...`` / ``- DO ...`` forms
        so rules written by ``evolve_skill`` (``- DO: rule``) round-trip.
        """
        rules = []
        import re

        for m in re.finditer(r"^[-*]\s+\*\*(DO|DON'T)\*\*:\s*(.+)$", body, re.MULTILINE):
            rules.append(f"{m.group(1)}: {m.group(2).strip()}")
        for m in re.finditer(r"^[-*]\s+(DO|DON'T)[\s:]+(.+)$", body, re.MULTILINE):
            rules.append(f"{m.group(1)}: {m.group(2).strip()}")
        return rules

    def _extract_procedures(self, body: str) -> list[dict]:
        """Extract structured procedure steps from the markdown body.

        Accepts ``- **1**: desc`` / ``- **step**: desc`` forms so both the
        builtin catalog and the LLM SkillArchitect contract
        (``{step, action, description}``) round-trip this shape.
        """
        procedures = []
        import re

        for m in re.finditer(r"^[-*]\s+\*\*([A-Za-z0-9_-]+)\*\*:\s*(.+)$", body, re.MULTILINE):
            procedures.append({"step": m.group(1), "description": m.group(2).strip()})
        return procedures

    def _store(self, data: dict, source: str = "") -> None:
        name = data.get("name", "unknown")
        data["source"] = source
        data["loaded_at"] = time.time()
        with self._lock:
            self._skills[name] = data

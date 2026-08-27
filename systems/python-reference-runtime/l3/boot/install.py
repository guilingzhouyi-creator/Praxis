"""Install — first-run and upgrade lifecycle phase.

Called from boot.py when should_install() returns True.
Performs schema migrations, seeds defaults, and marks version.
Also exposes a ``praxis-install`` console entry for installer-driven
first-run initialization on end-user devices (non-boot path).
"""

from __future__ import annotations

import argparse
import json
import logging
import time

from l1.kernel.lifecycle import LifecycleState, get_lifecycle
from l1.kernel.migration import SCHEMA_VERSION, run_pending
from l1.kernel.params.agent import CARD_TIMELINE_EXECUTION, CARD_TIMELINE_REVIEW

logger = logging.getLogger(__name__)


def install() -> dict:
    """Run first-install/upgrade steps and return a results dict."""
    lifecycle = get_lifecycle()
    lifecycle.load()

    if not lifecycle.transition(LifecycleState.INSTALLING):
        return {"success": False, "error": "cannot enter INSTALLING state"}

    results: dict = {}

    # 1. Schema migrations
    try:
        mig = run_pending(
            current=lifecycle._record.schema_version,
            target=SCHEMA_VERSION,
        )
        results["migrations"] = mig
    except Exception as e:
        results["migrations"] = {"error": str(e)}

    # 2. Ensure archive DB (idempotent)
    try:
        from l3.tools._archive import init_archive

        arch = init_archive()
        results["archive_init"] = arch.get("success", False)
    except Exception as e:
        results["archive_init"] = str(e)

    # 3. Seed archive defaults (first install only)
    try:
        if lifecycle._record.install_version == 0:
            from l3.tools._archive import _cmd_archive_store

            _cmd_archive_store(
                fonds="SYSTEM",
                series="lifecycle",
                content=json.dumps(
                    {
                        "event": "first_install",
                        "timestamp": time.time(),
                    }
                ),
                tags="system,lifecycle,first_install",
            )
            results["archive_seed"] = True
    except Exception as e:
        results["archive_seed"] = str(e)

    # 3b. Upgrade: merge new-template defaults into the existing user config
    # (user-set keys preserved, new-version keys filled with template values,
    # pre-merge config backed up as .bak). Runs only on schema upgrades, not
    # on first install — fresh installs get the full template via ensure_config.
    try:
        if lifecycle._record.install_version > 0 and lifecycle._record.schema_version != SCHEMA_VERSION:
            from l3.config.ensure_config import merge_config_templates

            mg = merge_config_templates()
            results["config_merge"] = mg
    except Exception as e:
        results["config_merge"] = {"error": str(e)}

    # 4. Seed card types if registry empty
    try:
        from l3.card.card_unified import list_card_types

        if not list_card_types():
            from l3.card.card_unified import register_card_type

            for name, defn in _CARD_TYPE_DEFAULTS.items():
                register_card_type(name, defn)
            results["card_types_seeded"] = list(_CARD_TYPE_DEFAULTS.keys())
    except Exception as e:
        results["card_types_seeded"] = str(e)

    # 5. Mark version
    lifecycle._record.install_version += 1
    lifecycle._record.schema_version = SCHEMA_VERSION
    from l1.kernel.params.system import KERNEL_VERSION

    lifecycle._record.app_version = KERNEL_VERSION
    lifecycle.save()

    lifecycle.transition(LifecycleState.BOOTING)

    logger.info(
        "install complete: version=%d schema=%s app=%s",
        lifecycle._record.install_version,
        lifecycle._record.schema_version,
        lifecycle._record.app_version,
    )
    return {
        "success": True,
        "results": results,
        "install_version": lifecycle._record.install_version,
        "schema_version": lifecycle._record.schema_version,
    }


def main() -> int:
    """praxis-install console entry: run first-install/upgrade steps.

    Intended for installer-driven first-run initialization on end-user
    devices: runs schema migrations, seeds defaults, and marks the installed
    version — the non-boot equivalent of the boot-time install phase.
    """
    parser = argparse.ArgumentParser(prog="praxis-install", description="Praxis first-install / upgrade lifecycle")
    parser.add_argument("--dry-run", action="store_true", help="report what would run without executing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if args.dry_run:
        print(f"praxis-install: dry-run (schema target={SCHEMA_VERSION})")
        return 0
    result = install()
    if not result.get("success"):
        print(f"praxis-install failed: {result.get('error', 'unknown')}")
        return 1
    print(f"praxis-install ok: install_version={result.get('install_version')} schema={result.get('schema_version')}")
    return 0


_CARD_TYPE_DEFAULTS: dict = {
    "execution": {
        "display": "Execution",
        "phases": ["plan", "implement", "verify"],
        "max_phases": 5,
        "concurrent_phases": False,
        "allow_fail": False,
        "timeline": CARD_TIMELINE_EXECUTION,
        "metadata_schema": {},
    },
    "review": {
        "display": "Review",
        "phases": ["review"],
        "max_phases": 1,
        "concurrent_phases": False,
        "allow_fail": True,
        "timeline": CARD_TIMELINE_REVIEW,
        "metadata_schema": {},
    },
    "issue": {
        "display": "Issue",
        "phases": ["triage", "resolve", "verify"],
        "max_phases": 5,
        "concurrent_phases": False,
        "allow_fail": True,
        "timeline": 86400,
        "metadata_schema": {},
    },
    "inspection": {
        "display": "Inspection",
        "phases": ["audit", "report"],
        "max_phases": 3,
        "concurrent_phases": False,
        "allow_fail": True,
        "timeline": 3600,
        "metadata_schema": {},
    },
}

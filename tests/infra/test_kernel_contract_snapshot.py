"""Kernel public-API contract snapshot (W6.3) — golden gate for l1_kernel_rs."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "py"))

_spec = importlib.util.spec_from_file_location(
    "gen_kernel_contract",
    ROOT / "scripts" / "py" / "gen_kernel_contract.py",
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def test_snapshot_in_sync() -> None:
    """The committed golden JSON must match the live kernel surface."""
    snapshot = gen.build_snapshot()
    live = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    golden = gen.GOLDEN.read_text(encoding="utf-8")
    assert live == golden, (
        "kernel contract snapshot drifted — run `python scripts/py/gen_kernel_contract.py --fix` and commit the golden",
    )


def test_golden_is_complete() -> None:
    """The golden must carry modules, syscalls and exports."""
    data = json.loads(gen.GOLDEN.read_text(encoding="utf-8"))
    assert data["contract_version"] == gen.CONTRACT_VERSION
    assert data["kernel_package"] == "l1.kernel"
    assert data["modules"], "no kernel modules captured"
    assert "l1.kernel.gatechain" in {m["module"] for m in data["modules"]}
    assert data["syscalls"], "no syscalls captured"
    assert "process.spawn" in data["syscalls"]
    assert "invoke_capability" in data["all_exports"], "capability syscall missing from exports"

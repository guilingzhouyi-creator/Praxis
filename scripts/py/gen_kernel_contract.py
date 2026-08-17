"""Generate/verify the kernel public-API contract snapshot (W6.3).

Scans ``src/l1/kernel`` (modules, public functions, public classes), the
syscall registry, and the ``l1.kernel`` ``__all__`` exports into a golden
JSON that ``l1_kernel_rs`` aligns against.

    python scripts/py/gen_kernel_contract.py          # check (CI gate)
    python scripts/py/gen_kernel_contract.py --fix    # regenerate golden
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC_KERNEL = ROOT / "src" / "l1" / "kernel"
GOLDEN = ROOT / "docs" / "contracts" / "kernel-contract.json"

CONTRACT_VERSION = 1


def _module_path(py: Path) -> str:
    """Relative import path, e.g. ``l1.kernel.params.gatechain``."""
    rel = py.relative_to(ROOT / "src").with_suffix("")
    return ".".join(rel.parts)


def _public_members(py: Path) -> dict:
    """Collect public functions and classes from one kernel module."""
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    funcs: list[str] = []
    classes: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            funcs.append(node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            classes.append(node.name)
    return {"functions": sorted(funcs), "classes": sorted(classes)}


def _syscall_ops() -> list[str]:
    """All registered syscall ops (builtin + dynamic)."""
    import l1.kernel as kernel

    return sorted(kernel._SYSCALL_REGISTRY.keys())


def _all_exports() -> list[str]:
    """Public names exported by ``l1.kernel`` ``__all__``."""
    import l1.kernel as kernel

    return sorted(kernel.__all__)


def _modules() -> list[dict]:
    """One entry per kernel module with its public members."""
    out: list[dict] = []
    for py in sorted(SRC_KERNEL.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        members = _public_members(py)
        if members["functions"] or members["classes"]:
            out.append({"module": _module_path(py), **members})
    return out


def build_snapshot() -> dict:
    """Assemble the full contract snapshot."""
    return {
        "contract_version": CONTRACT_VERSION,
        "kernel_package": "l1.kernel",
        "modules": _modules(),
        "syscalls": _syscall_ops(),
        "all_exports": _all_exports(),
    }


def main() -> int:
    """Check (default) or regenerate (--fix) the golden snapshot."""
    snapshot = build_snapshot()
    text = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    if "--fix" in sys.argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(text, encoding="utf-8")
        print(f"wrote {GOLDEN.relative_to(ROOT)}")
        return 0
    if not GOLDEN.exists():
        print(f"DRIFT: {GOLDEN.relative_to(ROOT)} missing — run with --fix", file=sys.stderr)
        return 1
    if GOLDEN.read_text(encoding="utf-8") != text:
        print("DRIFT: kernel contract snapshot out of date — run `python scripts/py/gen_kernel_contract.py --fix`")
        return 1
    print("Kernel contract snapshot is in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Memory-leak smoke check — repeated register/unregister must not grow memory.

Runs N cycles of tool register+unregister on the global TOOL_REGISTRY under
tracemalloc; a leak (specs or handler closures retained after unregister)
shows up as monotonic growth. Fails when growth per cycle exceeds the
budget. Catches the classic "unregister leaves the registry entry / handler
closure referenced" defect class in long-lived daemons and API processes.

Usage (from the repo root, exit code 1 on suspected leak):

    python scripts/py/mem-check.py
"""

from __future__ import annotations

import gc
import sys
import tracemalloc

# Imported at module scope (before tracemalloc.start() in main) so the
# one-time module-loading allocation is NOT counted as leak growth.
from l3.tool_system.tool_spec import TOOL_REGISTRY, ParamSpec, ToolRing, ToolSpec, register

CYCLES = 2000
# Per-cycle growth budget after GC — well above allocator noise, far below
# a real leak (a retained closure/spec costs hundreds of bytes).
GROWTH_LIMIT_BYTES = 512.0


def _run_cycles(n: int) -> None:
    def make_handler(i: int):
        def handler(args: dict, agent_id: str) -> dict:
            return {"success": True, "i": i}

        return handler

    for i in range(n):
        name = f"mem_check_{i}"
        spec = ToolSpec(
            name=name,
            description="memory-leak check spec",
            category="test",
            ring=ToolRing.RING_1,
            danger=1,
            handler=make_handler(i),
            parameters=[ParamSpec(name="p", type="string", description="p")],
        )
        register(spec)
        TOOL_REGISTRY.unregister(name)


def main() -> int:
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    _run_cycles(CYCLES)
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    growth = current - before
    per_cycle = growth / CYCLES
    print(f"cycles={CYCLES} growth={growth} bytes ({per_cycle:.1f} bytes/cycle) peak={peak}")
    tracemalloc.stop()
    if per_cycle > GROWTH_LIMIT_BYTES:
        print(f"❌ suspected leak: {per_cycle:.1f} bytes/cycle > {GROWTH_LIMIT_BYTES}")
        return 1
    print("✅ no significant memory growth")
    return 0


if __name__ == "__main__":
    sys.exit(main())

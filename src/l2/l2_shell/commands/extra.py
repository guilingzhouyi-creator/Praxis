"""L2 Shell: extended commands — domain-split facade.

Extracted into per-domain submodules (extra_cluster / extra_mcp /
extra_security / extra_resources / extra_stats); this module re-exports
every ``_cmd_*`` so ``commands/__init__.py`` and existing test imports
keep resolving unchanged.
"""

from __future__ import annotations

from .extra_cluster import (  # noqa: F401 — re-export for callers
    _cmd_cells,
    _cmd_cluster,
    _cmd_cross,
    _cmd_htn,
)
from .extra_mcp import _cmd_mcp  # noqa: F401 — re-export for callers
from .extra_resources import (  # noqa: F401 — re-export for callers
    _cmd_buffer,
    _cmd_think,
)
from .extra_security import _cmd_security  # noqa: F401 — re-export for callers
from .extra_stats import _cmd_stats  # noqa: F401 — re-export for callers

__all__ = [
    "_cmd_buffer",
    "_cmd_cells",
    "_cmd_cluster",
    "_cmd_cross",
    "_cmd_htn",
    "_cmd_mcp",
    "_cmd_security",
    "_cmd_stats",
    "_cmd_think",
]

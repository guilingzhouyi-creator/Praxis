"""Boot step implementations — packaged by domain.

Extracted from the monolithic ``boot_steps.py``: every ``_*`` boot step
function now lives in a domain module (constitution / discovery / config /
kernel / tools / runtime / services / cell / health) and is re-exported
here so ``from l3.boot.boot_steps import _load_constitution`` keeps
working — ``boot.py`` and tests import through this package unchanged.
"""

from __future__ import annotations

from .cell import _create_cell
from .config import _load_config
from .constitution import _default_constitution, _load_constitution
from .discovery import _init_discovery
from .health import _post_boot_health_check
from .kernel import _init_kernel_and_vfs
from .layout import _prepare_layout
from .runtime import _init_memory_and_archive, _init_skills_and_network, _init_system_bus
from .services import _init_services
from .shells import _init_shells
from .tools import _init_record_center, _load_dvg, _load_tools

__all__ = [
    "_create_cell",
    "_default_constitution",
    "_init_discovery",
    "_init_kernel_and_vfs",
    "_init_memory_and_archive",
    "_init_record_center",
    "_init_services",
    "_init_shells",
    "_init_skills_and_network",
    "_init_system_bus",
    "_load_config",
    "_load_constitution",
    "_load_dvg",
    "_load_tools",
    "_post_boot_health_check",
    "_prepare_layout",
]

"""Transition shim (WS5.3): implementation moved to l3.agent.prompts.

Keep this module importable so existing `from l1.kernel.prompts import ...`
call sites keep working; the Rust rewrite targets the new home.
"""

import importlib as _importlib
from typing import TYPE_CHECKING

# The runtime implementation lives in l3.agent.prompts (WS5.3 moved it out of
# kernel). This shim re-exports its symbols dynamically so old import paths
# keep working. mypy cannot see dynamic globals(), so the TYPE_CHECKING
# import below declares the surface statically — the annotation is never
# executed at runtime.
if TYPE_CHECKING:
    from l3.agent.prompts import (  # noqa: F401  (re-export surface)
        get_prompt,
        get_prompt_monitored,
        get_prompt_override,
        load_prompt_overrides,
        prompt_versioning_status,
        prompt_versions,
        restore_prompt_override,
        rollback_prompt,
    )

_m = _importlib.import_module("l3.agent.prompts")
globals().update({_k: _v for _k, _v in _m.__dict__.items() if not _k.startswith("__")})
del _m, _importlib

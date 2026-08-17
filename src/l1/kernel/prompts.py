"""Transition shim (WS5.3): implementation moved to l3.agent.prompts.

Keep this module importable so existing `from l1.kernel.prompts import ...`
call sites keep working; the Rust rewrite targets the new home.
"""

import importlib as _importlib

_m = _importlib.import_module("l3.agent.prompts")
globals().update({_k: _v for _k, _v in _m.__dict__.items() if not _k.startswith("__")})
del _m, _importlib

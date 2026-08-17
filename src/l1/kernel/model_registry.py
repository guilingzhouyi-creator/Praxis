"""Transition shim (WS5.2): implementation moved to l4.llm.model_registry.

Keep this module importable so existing `from l1.kernel.model_registry import ...`
call sites keep working; the Rust rewrite targets the new home.
"""

import importlib as _importlib

_m = _importlib.import_module("l4.llm.model_registry")
globals().update({_k: _v for _k, _v in _m.__dict__.items() if not _k.startswith("__")})
del _m, _importlib

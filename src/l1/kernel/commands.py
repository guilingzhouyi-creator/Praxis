"""Transition shim (WS5.3): implementation moved to l2.commands.

Keep this module importable so existing `from l1.kernel.commands import ...`
call sites keep working; the Rust rewrite targets the new home.
"""

import importlib as _importlib

_m = _importlib.import_module("l2.commands")
globals().update({_k: _v for _k, _v in _m.__dict__.items() if not _k.startswith("__")})
del _m, _importlib

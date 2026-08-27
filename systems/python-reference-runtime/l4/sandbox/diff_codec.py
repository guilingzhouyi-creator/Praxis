"""Diff record codec (2.1-D5) — structured envelope + zlib payload.

Stitched unified-diff text is highly repetitive (context lines, ``@@``
headers, ``---``/``+++`` markers). Empirically (benchmarked against a
multi-hunk corpus) zlib's LZ77 already captures all of that redundancy —
an explicit line-pool encoding measured *larger* (1.25–1.38×) than plain
zlib on the same corpus, so the codec does not fight the compressor.

What structure does buy us is the **envelope**: the record's fields
(``diff_id`` / ``ts`` / ``meta``) are dictionary-coded and stored
separately from the compressed text, so a decompressed record restores the
full structure without text re-parsing. The stream is prefixed with a
version magic so legacy plain-zlib records stay readable.

``compress_record`` / ``decompress_record`` are pure functions; the persist
store calls them at ring-eviction time. Decompression never raises on
corrupt input — it degrades to the raw text.
"""

from __future__ import annotations

import json
import logging
import zlib
from typing import Any

from l4.sandbox.diff_frame import (
    FLAG_HUNKS as _FLAG_HUNKS,
)
from l4.sandbox.diff_frame import (
    FLAG_SEMANTIC as _FLAG_SEMANTIC,
)
from l4.sandbox.diff_frame import (
    FRAME_REVIEW,
    build_frame_header,
    parse_frame_header,
)
from l4.sandbox.diff_frame import (
    HEADER_SIZE as _HEADER_SIZE,
)

logger = logging.getLogger(__name__)

# Version magic: marks structure-aware v2 payloads. Absence = legacy v1
# (plain zlib of the stitched text).
_MAGIC = b"PD2"

# Zstd-dict magic (Phase 2): L2 review frames compressed with the shared
# dictionary carry this prefix; decode requires the same dictionary.
_MAGIC_ZSTD = b"PDZ"

# AST tree-edit magic (Phase 3): frames carrying a tree-edit script
# (INS/DEL/MOV/UPD, see ast_edit.py) use this prefix.
_MAGIC_AST = b"PDA"

# Dictionary coding for repeated meta keys (shortened at rest).
_META_KEYS = {
    "diff_id": "d",
    "path": "p",
    "ts": "t",
}
_REVERSE_META_KEYS = {v: k for k, v in _META_KEYS.items()}


def _encode_meta(meta: dict | None) -> dict:
    """Shorten known meta keys (dictionary coding)."""
    if not meta:
        return {}
    return {_META_KEYS.get(k, k): v for k, v in meta.items()}


def _decode_meta(meta: dict | None) -> dict:
    """Restore original meta key names from the dictionary-coded form."""
    if not meta:
        return {}
    return {_REVERSE_META_KEYS.get(k, k): v for k, v in meta.items()}


# ── Hunk dictionary coding (enum-like fields → byte codes) ─────────────

# Hunk type codes (compute_hunks "type" field: replace/insert/delete).
_HUNK_TYPE_CODES = {"replace": 0, "insert": 1, "delete": 2}
_HUNK_TYPE_NAMES = {v: k for k, v in _HUNK_TYPE_CODES.items()}

# Semantic label codes (classify_hunk_semantic output).
_SEMANTIC_CODES = {
    "": 0,
    "structural": 1,
    "logic_change": 2,
    "reformat": 3,
    "rename": 4,
    "comment_only": 5,
    "import_change": 6,
    "import_added": 7,
    "mixed": 8,
}
_SEMANTIC_NAMES = {v: k for k, v in _SEMANTIC_CODES.items()}


def _encode_hunk(hunk: dict[str, Any], prev_start: int) -> tuple[dict[str, Any], int]:
    """Dictionary-code one hunk; returns (coded, modified_start for delta)."""
    mstart = int(hunk.get("modified_start", 0) or hunk.get("original_start", 0) or 0)
    coded = {
        "t": _HUNK_TYPE_CODES.get(str(hunk.get("type", "")), 0),
        "o": int(hunk.get("original_start", 0) or 0) - prev_start,  # row delta
        "m": mstart,
        "a": [ln.rstrip("\n") for ln in (hunk.get("added_lines") or [])],
        "r": [ln.rstrip("\n") for ln in (hunk.get("removed_lines") or [])],
    }
    sem = str(hunk.get("semantic", ""))
    if sem:
        coded["s"] = _SEMANTIC_CODES.get(sem, 0)
    return coded, mstart


def _decode_hunk(coded: dict[str, Any], prev_start: int) -> tuple[dict[str, Any], int]:
    """Reverse ``_encode_hunk`` into a hunk dict; returns (hunk, modified_start)."""
    mstart = int(coded.get("m", 0) or 0)
    hunk: dict[str, Any] = {
        "type": _HUNK_TYPE_NAMES.get(int(coded.get("t", 0)), "replace"),
        "original_start": int(coded.get("o", 0) or 0) + prev_start,
        "modified_start": mstart,
        "added_lines": [ln + "\n" for ln in (coded.get("a") or [])],
        "removed_lines": [ln + "\n" for ln in (coded.get("r") or [])],
    }
    if "s" in coded:
        hunk["semantic"] = _SEMANTIC_NAMES.get(int(coded.get("s", 0)), "")
    return hunk, mstart


def encode_hunks(
    hunks: list[dict[str, Any]],
    frame_type: int = FRAME_REVIEW,
    dictionary: bytes | None = None,
) -> bytes:
    """Encode structured hunks into a versioned frame with a plaintext header.

    Each hunk is dictionary-coded (type/semantic → byte codes, original
    start rows → delta) so the payload is compact; the 8-byte header stays
    plaintext for threshold fast-path reads.

    Compression tier (Phase 2): when a shared Zstd dictionary is supplied
    (and zstandard is importable) the payload uses zstd-dict (magic ``PDZ``)
    for the L2 review frame; otherwise it falls back to zlib (magic ``PD2``).
    """
    prev = 0
    coded_hunks: list[dict[str, Any]] = []
    for h in hunks:
        coded, prev = _encode_hunk(h, prev)
        coded_hunks.append(coded)
    bitmask = _FLAG_HUNKS
    if any("s" in c for c in coded_hunks):
        bitmask |= _FLAG_SEMANTIC
    payload = json.dumps({"h": coded_hunks}, ensure_ascii=False, separators=(",", ":"), default=str)
    header = build_frame_header(frame_type=frame_type, bitmask=bitmask, hunk_count=len(coded_hunks))
    raw = payload.encode("utf-8")
    if dictionary:
        try:
            import zstandard

            cctx = zstandard.ZstdCompressor(dict_data=zstandard.ZstdCompressionDict(dictionary))
            return header + _MAGIC_ZSTD + cctx.compress(raw)
        except Exception as e:
            logger.debug("diff_codec: zstd-dict compress skipped: %s", e)
    return header + _MAGIC + zlib.compress(raw)


def decode_hunks(binary: bytes, dictionary: bytes | None = None) -> list[dict[str, Any]]:
    """Decode a hunk frame back into hunk dicts (None header → []).

    Handles both the zlib frame (``PD2``) and the zstd-dict frame (``PDZ``,
    requiring the same shared dictionary used at encode time).
    """
    try:
        head = parse_frame_header(binary)
        if head is None or not (head["bitmask"] & _FLAG_HUNKS):
            return []
        body = binary[_HEADER_SIZE:]
        if body.startswith(_MAGIC_ZSTD):
            if not dictionary:
                return []
            import zstandard

            dctx = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(dictionary))
            payload = dctx.decompress(body[len(_MAGIC_ZSTD) :]).decode("utf-8")
        else:
            payload = zlib.decompress(body[len(_MAGIC) :]).decode("utf-8")
        coded_hunks = json.loads(payload).get("h", []) or []
        prev = 0
        hunks: list[dict[str, Any]] = []
        for c in coded_hunks:
            h, prev = _decode_hunk(c, prev)
            hunks.append(h)
        return hunks
    except Exception:
        return []


def encode_ast_script(
    script: bytes,
    frame_type: int = FRAME_REVIEW,
    dictionary: bytes | None = None,
    hunk_count: int = 0,
) -> bytes:
    """Encode an AST tree-edit script into a versioned frame (Phase 3).

    The 8-byte plaintext header (frame type / bitmask / score / op count)
    keeps the bypass fast path working for tree-edit frames too. The script
    payload (already Varint/Zigzag-coded by ``ast_edit.encode_script``) is
    compressed with the shared Zstd dictionary when available (``PDA`` +
    zstd), else zlib (``PDA`` + zlib — the AST magic distinguishes tree
    frames from hunk frames).
    """
    header = build_frame_header(frame_type=frame_type, bitmask=_FLAG_HUNKS, hunk_count=hunk_count)
    if dictionary:
        try:
            import zstandard

            cctx = zstandard.ZstdCompressor(dict_data=zstandard.ZstdCompressionDict(dictionary))
            return header + _MAGIC_AST + cctx.compress(script)
        except Exception as e:
            logger.debug("diff_codec: ast zstd-dict compress skipped: %s", e)
    return header + _MAGIC_AST + zlib.compress(script)


def decode_ast_script(binary: bytes, dictionary: bytes | None = None) -> bytes | None:
    """Decode an AST tree-edit frame back into the raw script bytes.

    Returns None for non-AST frames, short input, or corrupt payloads (the
    caller falls back to row-level hunks — never raises).
    """
    try:
        head = parse_frame_header(binary)
        if head is None:
            return None
        body = binary[_HEADER_SIZE:]
        if not body.startswith(_MAGIC_AST):
            return None
        raw = body[len(_MAGIC_AST) :]
        if dictionary:
            try:
                import zstandard

                dctx = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(dictionary))
                return dctx.decompress(raw)
            except Exception as e:
                logger.debug("diff_codec: ast zstd-dict decompress skipped: %s", e)
        return zlib.decompress(raw)
    except Exception:
        return None


def compress_record(record: dict[str, Any]) -> bytes:
    """Compress a structured diff-persist record into a versioned stream.

    Args:
        record: Ring record with ``diff_id`` / ``ts`` / ``meta`` / ``stitched``.

    Returns:
        ``b"PD2"`` + zlib payload: compact JSON envelope (dictionary-coded
        meta) with the stitched text as the compressible body.
    """
    envelope = json.dumps(
        {
            "d": record.get("diff_id", ""),
            "t": record.get("ts", 0.0),
            "m": _encode_meta(record.get("meta")),
            "s": str(record.get("stitched") or ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return _MAGIC + zlib.compress(envelope.encode("utf-8"))


def decompress_record(binary: bytes) -> dict[str, Any]:
    """Decompress a versioned stream back into a structured record.

    Legacy v1 payloads (plain ``zlib`` of the stitched text, no magic) are
    restored as ``{"stitched": <text>}``. Corrupt input degrades to the raw
    decoded text rather than raising.

    Returns:
        A record dict — at minimum containing ``stitched``.
    """
    try:
        if binary.startswith(_MAGIC):
            payload = json.loads(zlib.decompress(binary[len(_MAGIC) :]).decode("utf-8"))
            return {
                "diff_id": payload.get("d", ""),
                "ts": payload.get("t", 0.0),
                "meta": _decode_meta(payload.get("m")),
                "stitched": payload.get("s", ""),
            }
        # Legacy v1: plain zlib of the stitched text.
        return {"stitched": zlib.decompress(binary).decode("utf-8", errors="replace")}
    except Exception:
        return {"stitched": binary.decode("utf-8", errors="replace")}

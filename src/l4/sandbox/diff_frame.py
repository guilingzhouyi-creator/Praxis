"""Diff frame header (Phase 1) — 8-byte plaintext header for fast-path reads.

The diff frame (encoded structured hunks) carries a fixed 8-byte header at
the front that is deliberately **not** compressed, so the bypass monitor can
read frame type / bitmask flags / threshold score / hunk count without
decompressing the payload — nanoseconds instead of a zlib round-trip.

Lives in L1 because both L3 (review_pipeline bypass monitor) and L4
(diff_codec encoder) consume it; a pure-bytes module with zero dependencies.

Layout::
    byte 0      frame_type (1 = build, 2 = review, 3 = conflict)
    byte 1      bitmask flags (bit0 = has hunks, bit1 = has meta,
                               bit2 = has semantic labels)
    bytes 2-3   threshold_score (u16 big-endian)
    bytes 4-7   hunk_count (u32 big-endian)
"""

from __future__ import annotations

from typing import Any

# Frame types (three-tier topology): 1 = build, 2 = review, 3 = conflict.
FRAME_BUILD = 1
FRAME_REVIEW = 2
FRAME_CONFLICT = 3

# Bitmask flags inside the frame header.
FLAG_HUNKS = 0x01  # payload carries structured hunks
FLAG_META = 0x02  # payload carries meta (dictionary-coded)
FLAG_SEMANTIC = 0x04  # hunks carry semantic labels

HEADER_SIZE = 8


def build_frame_header(
    frame_type: int = FRAME_REVIEW,
    threshold_score: int = 0,
    bitmask: int = 0,
    hunk_count: int = 0,
) -> bytes:
    """Build the 8-byte plaintext frame header (bounded-read fast path).

    Args:
        frame_type: One of FRAME_BUILD / FRAME_REVIEW / FRAME_CONFLICT.
        threshold_score: Bypass threshold score carried for fast reads.
        bitmask: FLAG_* bits describing the payload.
        hunk_count: Number of hunks in the payload.

    Returns:
        8 bytes: type, flags, u16 BE score, u32 BE hunk count.
    """
    return bytes(
        [
            frame_type & 0xFF,
            bitmask & 0xFF,
            (threshold_score >> 8) & 0xFF,
            threshold_score & 0xFF,
            (hunk_count >> 24) & 0xFF,
            (hunk_count >> 16) & 0xFF,
            (hunk_count >> 8) & 0xFF,
            hunk_count & 0xFF,
        ]
    )


def parse_frame_header(binary: bytes) -> dict[str, int] | None:
    """Parse the 8-byte header without decompressing (None on short input).

    Args:
        binary: The raw frame bytes (header must be the first 8 bytes).

    Returns:
        ``{"frame_type", "bitmask", "threshold_score", "hunk_count"}`` or
        None when the input is shorter than the header.
    """
    if not binary or len(binary) < HEADER_SIZE:
        return None
    return {
        "frame_type": binary[0],
        "bitmask": binary[1],
        "threshold_score": (binary[2] << 8) | binary[3],
        "hunk_count": (binary[4] << 24) | (binary[5] << 16) | (binary[6] << 8) | binary[7],
    }


def header_for_record(record: dict[str, Any]) -> bytes:
    """Build a frame header from a ring record's hunk list (best-effort).

    Convenience for callers that hold the record rather than the encoded
    frame: derives the hunk count and semantic flag from the record.
    """
    hunks = record.get("hunks") or []
    bitmask = FLAG_HUNKS
    if any(h.get("semantic") for h in hunks):
        bitmask |= FLAG_SEMANTIC
    if record.get("meta"):
        bitmask |= FLAG_META
    return build_frame_header(
        frame_type=FRAME_REVIEW,
        threshold_score=int(record.get("ts", 0.0) or 0),
        bitmask=bitmask,
        hunk_count=len(hunks),
    )

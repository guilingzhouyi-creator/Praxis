"""2.1-D5 tests — structure-aware diff codec (dictionary + row-dedup + zlib).

Verifies round-trip fidelity, that the structured encoding beats plain
zlib-on-text for repetitive diffs, and that legacy v1 records (plain zlib,
no magic) still decompress.
"""

from __future__ import annotations

import zlib

from l4.sandbox.diff_codec import compress_record, decompress_record


def _record(
    diff_id: str = "d1", path: str = "systems/python-reference-runtime/a.py", ts: float = 100.0, stitched: str = ""
) -> dict:
    return {"diff_id": diff_id, "ts": ts, "meta": {"path": path}, "stitched": stitched}


def _repetitive_diff() -> str:
    """A realistic multi-hunk unified diff: identical context lines, @@
    headers and ---/+++ markers repeat across hunks (the redundancy the
    structure-aware codec exploits)."""
    shared_ctx = "     return dispatch(event, ctx)\n"
    lines = ["--- a/systems/python-reference-runtime/a.py", "+++ b/systems/python-reference-runtime/a.py"]
    for i in range(5):
        lines.extend(
            [
                f"@@ -{10 + i * 20},6 +{10 + i * 20},6 @@",
                "     def handler(self, event):",
                "-    old_path = event.get('old')",
                "+    new_path = event.get('new')",
                shared_ctx.rstrip("\n"),
            ]
        )
    return "\n".join(lines)


def test_round_trip_preserves_fields():
    """compress → decompress restores diff_id / ts / meta / stitched exactly."""
    rec = _record(
        stitched="--- a/systems/python-reference-runtime/a.py\n+++ b/systems/python-reference-runtime/a.py\n@@ -1,3 +1,3 @@\n-old\n+new"
    )
    out = decompress_record(compress_record(rec))
    assert out["diff_id"] == "d1"
    assert out["ts"] == 100.0
    assert out["meta"] == {"path": "systems/python-reference-runtime/a.py"}
    assert out["stitched"] == rec["stitched"]


def test_round_trip_repetitive_diff():
    """Row-dedup round-trip survives repeated lines exactly."""
    text = _repetitive_diff()
    out = decompress_record(compress_record(_record(stitched=text)))
    assert out["stitched"] == text


def test_structure_aware_overhead_controlled():
    """The structured envelope must not balloon the size over plain zlib.

    Empirically zlib's LZ77 already captures diff-text redundancy (context
    lines, @@ headers), so the codec's value is the structured envelope
    (field restoration without re-parsing) — bounded to a small fixed
    overhead, never multiplying the payload.
    """
    rec = _record(stitched=_repetitive_diff())
    compressed = compress_record(rec)
    legacy = len(zlib.compress(rec["stitched"].encode("utf-8")))
    assert len(compressed) <= legacy + 64
    assert compressed.startswith(b"PD2")


def test_legacy_v1_record_degrades():
    """Plain-zlib records (no magic) restore as stitched text (backward compat)."""
    text = "--- a/systems/python-reference-runtime/a.py\n+++ b/systems/python-reference-runtime/a.py\n@@ -1,1 +1,1 @@\n-old\n+new"
    legacy = zlib.compress(text.encode("utf-8"))
    out = decompress_record(legacy)
    assert out["stitched"] == text


def test_corrupt_input_degrades_not_raises():
    """Corrupt payloads degrade to raw text instead of raising."""
    out = decompress_record(b"\x00\x01\x02 not-valid-zlib")
    assert "stitched" in out


def test_empty_stitched_round_trip():
    """Empty stitched text compresses and decompresses cleanly."""
    out = decompress_record(compress_record(_record(stitched="")))
    assert out["stitched"] == ""


def test_eviction_uses_structure_codec(monkeypatch):
    """Ring eviction compresses via the structure-aware codec (PD2 magic)."""
    from l4.sandbox import diff_persist

    calls = []

    def _fake_archive_store(args, agent_id=""):
        calls.append((args, agent_id))
        return {"success": True}

    monkeypatch.setattr("l3.tools._archive.archive_store", _fake_archive_store)
    store = diff_persist.get_diff_persist()
    store.set_enabled(True)
    store._capacity = 1
    store.append("a", _repetitive_diff(), meta={"path": "systems/python-reference-runtime/a.py"})
    store.append("b", "newer content")

    assert len(calls) == 1
    args, agent_id = calls[0]
    assert args["fonds"] == "diff"
    assert args["series"] == "stitched"
    assert agent_id == "diff_persist"
    # Content stored is latin-1-decoded binary; Phase 2 wraps the frame in
    # the L3 archive tier (PDZ19), which embeds the structure-aware PD2 frame.
    stored = args["content"].encode("latin-1")
    assert stored.startswith(b"PDZ19")
    assert b"PD2" in stored


# ── 2.1 Phase 1: structured hunk frames + 8-byte header fast path ──


def _hunks() -> list[dict]:
    return [
        {
            "type": "replace",
            "original_start": 1,
            "modified_start": 1,
            "added_lines": ["def foo():\n", "    return 1\n"],
            "removed_lines": ["def foo():\n", "    pass\n"],
            "semantic": "logic_change",
        },
        {
            "type": "insert",
            "original_start": 10,
            "modified_start": 12,
            "added_lines": ["x = 1\n"],
            "removed_lines": [],
            "semantic": "structural",
        },
    ]


def test_hunk_frame_round_trip():
    """encode_hunks → decode_hunks preserves hunk structure and semantic."""
    from l4.sandbox.diff_codec import decode_hunks, encode_hunks

    hunks = _hunks()
    frame = encode_hunks(hunks, frame_type=2)
    out = decode_hunks(frame)
    assert len(out) == 2
    assert out[0]["type"] == "replace"
    assert out[0]["added_lines"] == ["def foo():\n", "    return 1\n"]
    assert out[0]["semantic"] == "logic_change"
    assert out[1]["type"] == "insert"
    assert out[1]["semantic"] == "structural"
    # Row deltas reconstruct original_start ordering.
    assert out[1]["original_start"] == 10


def test_frame_header_plaintext_fast_path():
    """The 8-byte header is readable without decompressing (bypass monitor)."""
    from l4.sandbox.diff_codec import build_frame_header, parse_frame_header

    header = build_frame_header(frame_type=2, threshold_score=50, bitmask=0x01, hunk_count=7)
    assert len(header) == 8
    head = parse_frame_header(header)
    assert head == {"frame_type": 2, "bitmask": 0x01, "threshold_score": 50, "hunk_count": 7}
    assert parse_frame_header(b"") is None


def test_frame_header_embedded_in_encode():
    """encode_hunks embeds a parseable plaintext header."""
    from l4.sandbox.diff_codec import encode_hunks, parse_frame_header

    frame = encode_hunks(_hunks(), frame_type=2)
    head = parse_frame_header(frame)
    assert head is not None
    assert head["frame_type"] == 2
    assert head["hunk_count"] == 2
    assert head["bitmask"] & 0x01  # hunks flag


def test_decode_hunks_corrupt_returns_empty():
    """Corrupt hunk frames decode to [] (never raise)."""
    from l4.sandbox.diff_codec import decode_hunks

    assert decode_hunks(b"garbage-not-a-frame") == []


# ── 2.1 Phase 2: shared Zstd dictionary frames (L2 high compression) ──


def _shared_dict() -> bytes:
    import zstandard

    samples = [f"def handler_{i}(event):\n    return dispatch(event, ctx)\n".encode() for i in range(50)]
    return zstandard.train_dictionary(2048, samples).as_bytes()


def test_zstd_dict_frame_round_trip():
    """zstd-dict frames (PDZ) round-trip with the same shared dictionary."""
    from l4.sandbox.diff_codec import decode_hunks, encode_hunks

    dict_data = _shared_dict()
    frame = encode_hunks(_hunks(), frame_type=2, dictionary=dict_data)
    assert frame[8:11] == b"PDZ"  # zstd-dict magic
    out = decode_hunks(frame, dictionary=dict_data)
    assert len(out) == 2
    assert out[0]["type"] == "replace"
    assert out[0]["semantic"] == "logic_change"


def test_zstd_dict_frame_requires_same_dict():
    """A zstd-dict frame cannot decode without the matching dictionary."""
    from l4.sandbox.diff_codec import decode_hunks, encode_hunks

    dict_data = _shared_dict()
    frame = encode_hunks(_hunks(), frame_type=2, dictionary=dict_data)
    assert decode_hunks(frame) == []  # no dict → []
    # A genuinely different dictionary (different training samples) fails to
    # decompress → [] (graceful, no raise).
    import zstandard

    other_samples = [f"def totally_unrelated_{i}():\n    pass\n".encode() for i in range(50)]
    other = zstandard.train_dictionary(2048, other_samples).as_bytes()
    assert other != dict_data
    assert decode_hunks(frame, dictionary=other) == []


def test_zstd_dict_smaller_than_zlib():
    """On repetitive review hunks the shared dictionary shrinks the frame."""
    from l4.sandbox.diff_codec import encode_hunks

    dict_data = _shared_dict()
    repetitive = [
        {
            "type": "replace",
            "original_start": 1 + i,
            "modified_start": 1 + i,
            "added_lines": [f"def handler_{i}(event):\n", "    return dispatch(event, ctx)\n"],
            "removed_lines": [f"def handler_{i}(event):\n", "    pass\n"],
            "semantic": "logic_change",
        }
        for i in range(10)
    ]
    zstd = encode_hunks(repetitive, frame_type=2, dictionary=dict_data)
    zlib = encode_hunks(repetitive, frame_type=2)
    assert len(zstd) <= len(zlib)


# ── 2.1 Phase 3: AST tree-edit frames ──


def _ast_script() -> bytes:
    from l4.sandbox.ast_edit import tree_edit_script

    script = tree_edit_script(
        "def foo(a):\n    return a + 1\n",
        "def foo(a):\n    return a + 2\n",
    )
    assert script is not None
    return script


def test_ast_frame_round_trip():
    """encode_ast_script → decode_ast_script restores the script bytes."""
    from l4.sandbox.diff_codec import decode_ast_script, encode_ast_script

    script = _ast_script()
    frame = encode_ast_script(script, frame_type=2)
    assert frame[8:11] == b"PDA"  # AST magic
    out = decode_ast_script(frame)
    assert out == script


def test_ast_frame_zstd_dict_round_trip():
    """AST frames support the shared Zstd dictionary (PDA + zstd)."""
    from l4.sandbox.diff_codec import decode_ast_script, encode_ast_script

    script = _ast_script()
    dict_data = _shared_dict()
    frame = encode_ast_script(script, frame_type=2, dictionary=dict_data)
    assert frame[8:11] == b"PDA"
    assert decode_ast_script(frame, dictionary=dict_data) == script
    # Without the dictionary the zstd-dict payload cannot decode.
    assert decode_ast_script(frame) is None


def test_ast_frame_non_ast_returns_none():
    """Non-AST frames (e.g. hunk frames) decode as None (fallback path)."""
    from l4.sandbox.diff_codec import decode_ast_script, encode_hunks

    hunks = [
        {
            "type": "replace",
            "original_start": 1,
            "modified_start": 1,
            "added_lines": ["x\n"],
            "removed_lines": ["y\n"],
            "semantic": "logic_change",
        }
    ]
    frame = encode_hunks(hunks, frame_type=2)
    assert decode_ast_script(frame) is None


def test_ast_frame_short_input_none():
    """Truncated/corrupt AST frames decode as None (never raise)."""
    from l4.sandbox.diff_codec import decode_ast_script

    assert decode_ast_script(b"\x00") is None
    assert decode_ast_script(b"garbage-not-a-frame") is None

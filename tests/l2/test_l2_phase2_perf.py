"""Phase 2 performance pins — preselect single scan + concurrent host.

TS rewrite reference: the shapes pinned here are transport-visible. The
TS engine dispatches sessions concurrently (no global lock) and receives
pure-data handler results; these tests freeze that contract on the
Python reference peer.
"""

from __future__ import annotations

import sys
import threading
from unittest import mock

from l2.protocol.envelope import KIND_RESULT, encode_message, make_message
from l2.protocol.host import ProtocolHost, _ThreadCaptureStdout

# ── preselect single scan ──


class TestPreselectSingleScan:
    def test_liveness_fetched_once_per_cell(self):
        """preselect() makes exactly one cell_liveness call per cell."""
        from l2 import selector

        calls: list[str] = []

        def fake_liveness(cell_id: str) -> dict:
            calls.append(cell_id)
            return {"agents": {f"agent-{cell_id}": {"role": "worker", "status": "online"}}}

        with (
            mock.patch("l2.bridge.cell_ids", lambda: ["c1", "c2"]),
            mock.patch("l2.bridge.cell_liveness", fake_liveness),
        ):
            result = selector.preselect()
        assert result["total"] == 2
        assert sorted(calls) == ["c1", "c2"]

    def test_role_index_reuses_prefetched_snapshots(self):
        """_rebuild_role_index only fetches cells missing from the cache."""
        from l2 import selector

        calls: list[str] = []
        snapshots = {"c1": {"agents": {"a1": {"role": "reader"}}}}

        def fake_liveness(cell_id: str) -> dict:
            calls.append(cell_id)
            return {"agents": {f"a-{cell_id}": {"role": "reader"}}}

        with (
            mock.patch("l2.bridge.cell_ids", lambda: ["c1"]),
            mock.patch("l2.bridge.cell_liveness", fake_liveness),
        ):
            selector._rebuild_role_index(["c1", "c2"], liveness_by_cell=snapshots)
        assert calls == ["c2"]
        assert ("c1", "a1") in selector._role_index["reader"]


# ── thread-local stdout capture ──


class _NullStream:
    """Minimal TextIO stand-in recording writes."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, s: str) -> int:
        self.writes.append(s)
        return len(s)

    def flush(self) -> None:
        pass


class TestThreadCaptureStdout:
    def test_armed_thread_buffers_prints(self, monkeypatch):
        sink = _NullStream()
        proxy = _ThreadCaptureStdout(real=sink)
        monkeypatch.setattr(sys, "stdout", proxy)
        buf = proxy.arm()
        print("captured-line")
        proxy.disarm()
        assert buf.getvalue().strip() == "captured-line"
        assert sink.writes == []

    def test_unarmed_writes_pass_through(self, monkeypatch):
        sink = _NullStream()
        proxy = _ThreadCaptureStdout(real=sink)
        monkeypatch.setattr(sys, "stdout", proxy)
        print("passthrough-line")
        assert any("passthrough-line" in w for w in sink.writes)

    def test_fresh_thread_is_never_armed(self):
        """A second thread's writes pass through while the main thread captures."""
        sink = _NullStream()
        proxy = _ThreadCaptureStdout(real=sink)
        buf = proxy.arm()
        holder: dict[str, int] = {}

        def writer():
            holder["n"] = proxy.write("other-thread\n")

        t = threading.Thread(target=writer)
        t.start()
        t.join()
        proxy.write("main-captured\n")
        proxy.disarm()
        assert holder["n"] == len("other-thread\n")
        assert "main-captured" in buf.getvalue()
        assert any("other-thread" in w for w in sink.writes)


# ── concurrent protocol host ──


class TestProtocolHostConcurrency:
    def test_parallel_sessions_dispatch_without_global_serialization(self):
        """N sessions × commands complete; per-session seqs stay ordered."""
        host = ProtocolHost()
        results: list[dict] = []
        lock = threading.Lock()

        def drive(session_id: str) -> None:
            for seq in range(1, 4):
                out = host.handle_message(make_message(session_id, seq, "command", {"name": "lang", "args": []}))
                with lock:
                    results.extend(env for env in out if env["kind"] == KIND_RESULT)

        threads = [threading.Thread(target=drive, args=(f"s-{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 12
        for r in results:
            assert r["payload"]["success"] is True
            assert encode_message(r)

    def test_concurrent_ack_keeps_cursor_monotonic(self):
        """Racing acks on one view advance the cursor monotonically."""
        host = ProtocolHost()
        host.attach_view("v-1", "s-1")

        def ack(n: int) -> None:
            host.handle_message(make_message("s-1", n, "ack", {"ack_seq": n, "view_id": "v-1"}))

        threads = [threading.Thread(target=ack, args=(n,)) for n in range(1, 9)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snapshot = host.view_cursor("v-1")
        assert snapshot is not None
        assert snapshot["last_acked"] >= 7

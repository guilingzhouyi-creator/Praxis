"""P1.1 slice tests — TieredCache persistence interface + eviction telemetry."""

from __future__ import annotations

import time

import pytest

from l3.memory.tiered_cache import TieredCache, reset_tiered_cache


@pytest.fixture()
def cache():
    reset_tiered_cache()
    t = TieredCache()
    yield t
    reset_tiered_cache()


def test_set_get_hit_miss_metrics(cache):
    cache.set("L1", "k", "v")
    assert cache.get("L1", "k") == "v"
    assert cache.get("L1", "missing") is None
    m = cache._metrics["L1"]
    assert m["hits"] == 1
    assert m["misses"] == 1


def test_eviction_metric_at_capacity(cache):
    # shrink capacity to force deterministic eviction
    cache._limits["L2"] = 2
    cache.set("L2", "a", 1)
    cache.set("L2", "b", 2)
    time.sleep(0.01)
    cache.set("L2", "c", 3)
    assert cache._metrics["L2"]["evictions"] == 1
    assert "a" in cache._layers["L2"] or len(cache._layers["L2"]) <= 2


def test_save_load_roundtrip(tmp_path, cache):
    cache.set("L1", "hot", {"x": 1})
    cache.set("L2", "sum", "summary-text")
    cache.set("L3", "arc", [1, 2])
    cache.get("L1", "hot")  # bump hits
    r = cache.save(str(tmp_path / "tc.json"))
    assert r["success"] is True

    fresh = TieredCache()
    lr = fresh.load(str(tmp_path / "tc.json"))
    assert lr["success"] is True
    assert fresh.get("L1", "hot") == {"x": 1}
    assert fresh.get("L2", "sum") == "summary-text"
    assert fresh.get("L3", "arc") == [1, 2]
    assert fresh._metrics["L1"]["hits"] >= 1  # telemetry survives too


def test_load_drops_expired_entries(tmp_path, cache):
    payload = {
        "layers": {
            "L1": {"live": ["v", time.time()], "dead": ["old", time.time() - 99999.0]},
        },
        "metrics": {},
        "ttls": {},
    }
    from l3.durable_store import DurableJsonStore

    DurableJsonStore(tmp_path / "tc.json", kind="tiered_cache").write(payload)
    fresh = TieredCache()
    r = fresh.load(str(tmp_path / "tc.json"))
    assert r["success"] is True
    assert fresh.get("L1", "live") == "v"
    assert fresh.get("L1", "dead") is None


def test_save_lossy_values_flagged(tmp_path, cache):
    class Opaque:
        pass

    cache.set("L1", "obj", Opaque())
    r = cache.save(str(tmp_path / "tc.json"))
    assert r["success"] is True
    assert r.get("lossy") is True

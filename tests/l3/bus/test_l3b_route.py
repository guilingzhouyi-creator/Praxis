"""Tests for l3.bus.l3b_composite.L3BComposite.route_subtask — HTN-B decomposition."""

from __future__ import annotations


class TestL3BRouteSubtask:
    """HTN-B route decomposition — row plan, enrichment, fallback."""

    def _make_composite(self):
        from l3.bus.l3b_composite import L3BComposite

        return L3BComposite("cell-1", "cell-2")

    def test_route_subtask_decomposes_route_forward(self):
        """A subtask containing routing keywords yields a check-prev + route plan."""
        c = self._make_composite()
        rows = c.route_subtask({"name": "forward this to next cell", "domain": "app/route"}, "prev-l2-summary")
        assert rows, "plan must not be empty"
        assert len(rows) >= 2
        check_prev = [r for r in rows if "check-prev" in r["id"]]
        route = [r for r in rows if r.get("tool") == "dispatch_to_next"]
        assert check_prev, "expected a check-prev row"
        assert route, "expected a dispatch_to_next row"
        # prev_summary must be attached to the check-prev step params.
        assert check_prev[0]["params"].get("prev_summary") == "prev-l2-summary"
        assert route[0]["params"]["target_cell"] == "cell-2"

    def test_route_subtask_unmatched_falls_back(self):
        """A subtask with no routing keyword is routed directly, never dropped."""
        c = self._make_composite()
        rows = c.route_subtask({"name": "analyze cost estimate", "domain": "app/x"}, "")
        assert len(rows) == 1
        assert rows[0]["tool"] == "dispatch_to_next"
        assert rows[0]["id"].endswith("-route")
        assert rows[0]["params"]["target_cell"] == "cell-2"

    def test_route_subtask_fallback_on_decompose_failure(self):
        """When decomposition raises, the direct-dispatch fallback still fires."""
        c = self._make_composite()

        def _boom(*args, **kwargs):
            raise RuntimeError("planner unavailable")

        c.htn_b.decompose = _boom
        rows = c.route_subtask({"name": "dispatch next", "domain": "app/route"}, "")
        assert len(rows) == 1
        assert rows[0]["tool"] == "dispatch_to_next"
        assert rows[0]["params"]["target_cell"] == "cell-2"

    def test_route_subtask_accepts_task_object(self):
        """A Task instance subtask is normalized via its fields."""
        from l3.bus.htn_planner import Task

        c = self._make_composite()
        rows = c.route_subtask(Task(id="t1", name="dispatch next", domain="app/route"), "")
        assert rows
        assert any(r.get("tool") == "dispatch_to_next" for r in rows)

    def test_route_subtask_accepts_string(self):
        """A plain-string subtask is treated as the intent name."""
        c = self._make_composite()
        rows = c.route_subtask("dispatch next", "")
        assert rows

    def test_route_subtask_no_prev_summary_enrichment(self):
        """Without a prev_summary, check-prev rows carry no summary key."""
        c = self._make_composite()
        rows = c.route_subtask({"name": "forward to next", "domain": "app/route"}, "")
        check_prev = [r for r in rows if "check-prev" in r["id"]]
        assert check_prev
        assert "prev_summary" not in check_prev[0]["params"]

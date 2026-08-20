"""L3 adapters for automation trace, metrics, evidence, and DVG ports."""

from __future__ import annotations

from typing import Any

from l1.kernel.ports import DependencyGraphPort, EvidencePort, ObservabilityPort, TracePort, register_port


class RuntimeObservabilityAdapter(ObservabilityPort):
    """Bridge the stable observability port to the L3 metrics facade."""

    def emit_count(self, name: str, value: int = 1, *, tags: dict[str, Any] | None = None) -> None:
        """Forward a counter to the best-effort L3 observability facade."""
        from l3.services.observability import emit_count

        emit_count(name, value, tags=tags)

    def emit_duration(self, name: str, started: float, *, tags: dict[str, Any] | None = None) -> None:
        """Forward a duration to the best-effort L3 observability facade."""
        from l3.services.observability import emit_duration

        emit_duration(name, started, tags=tags)


class RuntimeEvidenceAdapter(EvidencePort):
    """Bridge the stable evidence port to the L3 security evidence facade."""

    def record_evidence(
        self,
        phase: str,
        *,
        gate: str = "",
        decision: str = "ALLOW",
        target: str = "",
        source: str = "",
        tags: dict[str, str] | None = None,
        raw: dict[str, Any] | None = None,
        chain_kind: str = "",
    ) -> str:
        """Forward one evidence record to the L3 facade."""
        from l3.tool_system.security_evidence import record_evidence

        return record_evidence(
            phase=phase,
            gate=gate,
            decision=decision,
            target=target,
            source=source,
            tags=tags,
            raw=raw,
            chain_kind=chain_kind,
        )


class RuntimeDependencyGraphAdapter(DependencyGraphPort):
    """Bridge graph planning to the runtime DVG without exposing DVG to callers."""

    def plan(self, nodes: dict[str, tuple[str, ...]]) -> list[str]:
        """Return a validated DVG topological order for *nodes*."""
        from l3.tool_system.dvg import DvgGraph

        names = set(nodes)
        unknown = sorted(
            {dependency for dependencies in nodes.values() for dependency in dependencies if dependency not in names}
        )
        if unknown:
            raise ValueError(f"dependency graph contains unknown nodes: {', '.join(unknown)}")
        graph = DvgGraph()
        for name, dependencies in nodes.items():
            if not graph.register_tool_deps(name, list(dependencies)):
                raise ValueError(f"dependency graph contains a cycle involving '{name}'")
        order = graph.topo_order()
        if set(order) != names:
            raise ValueError("dependency graph planner returned an incomplete order")
        return order


class RuntimeTraceAdapter(TracePort):
    """Bridge trace scoping to the L3 error-bus context manager."""

    def scope(self, trace_id: str):
        """Return the L3 trace scope for *trace_id*."""
        from l3.error_bus.trace import trace_scope

        return trace_scope(trace_id)


def wire_automation_ports() -> dict[str, str]:
    """Register runtime adapters for automation side channels."""
    adapters = {
        "observability": RuntimeObservabilityAdapter(),
        "evidence": RuntimeEvidenceAdapter(),
        "dependency_graph": RuntimeDependencyGraphAdapter(),
        "trace": RuntimeTraceAdapter(),
    }
    for name, adapter in adapters.items():
        register_port(name, adapter)
    return {name: type(adapter).__name__ for name, adapter in adapters.items()}


__all__ = [
    "RuntimeDependencyGraphAdapter",
    "RuntimeEvidenceAdapter",
    "RuntimeObservabilityAdapter",
    "RuntimeTraceAdapter",
    "wire_automation_ports",
]

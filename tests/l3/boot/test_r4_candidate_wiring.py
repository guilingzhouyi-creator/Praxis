"""R4 candidate ledger port wiring tests."""

from __future__ import annotations


def test_default_wiring_registers_candidate_ledger_port():
    """Boot wiring exposes the candidate lifecycle without L2 importing L3."""
    from l1.kernel.ports import get_port, reset_ports
    from l3.boot.wiring import wire_defaults

    reset_ports()
    try:
        registry = wire_defaults()
        port = get_port("r4_candidates")

        assert registry["r4_candidates"] == "r4_candidate_ledger"
        assert callable(port.list_candidates)
    finally:
        reset_ports()

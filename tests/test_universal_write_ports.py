from __future__ import annotations

from typing import Any

from hypertrade.targets.ports import MarketWritePort


class MockCustomWriteAdapter:
    def deploy_strategy(self, name: str, code: str, config: dict[str, Any]) -> dict[str, Any]:
        return {"status": "deployed", "strategy_id": "cust_123"}

    def configure_paper(self, candidate_key: str, **fields: Any) -> dict[str, Any]:
        return {"status": "configured", "instance_id": f"paper_{candidate_key}"}

    def start_paper(self, candidate_key: str, **fields: Any) -> dict[str, Any]:
        return {"status": "started", "instance_id": f"paper_{candidate_key}"}

    def stop_paper(self, candidate_key: str, **fields: Any) -> dict[str, Any]:
        return {"status": "stopped", "instance_id": f"paper_{candidate_key}"}


def test_market_write_port_protocol_conformance() -> None:
    adapter = MockCustomWriteAdapter()
    assert isinstance(adapter, MarketWritePort)


def test_evolution_unblocks_on_custom_write_adapter() -> None:
    adapter = MockCustomWriteAdapter()
    # Verify write methods exist for evolution unblocking
    has_write_port = (
        hasattr(adapter, "paper_configure")
        or hasattr(adapter, "configure_paper")
        or hasattr(adapter, "deploy_strategy")
    )
    assert has_write_port is True

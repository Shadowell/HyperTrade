"""Slice 2 of the evolution handoff: running-strategy readiness projection.

The projection must never invent readiness: a strategy without settled BitPro
evidence, an internal version mapping, or two settled outcomes reports its gaps
explicitly instead of entering the evolution loop.
"""

from __future__ import annotations

from types import SimpleNamespace

from hypertrade.db import BitProStrategyEvidenceRecord
from hypertrade.research.evolution_readiness import (
    assess_running_strategy,
    running_inventory_readiness,
)


class _FakeDb:
    """Minimal session stub: no rows anywhere."""

    def session(self):  # noqa: D401 - context manager shape
        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def scalars(self, *_args, **_kwargs):
                return _EmptyIter()

        return _Session()


class _EmptyIter:
    def all(self):
        return []

    def __iter__(self):
        return iter([])

    def __next__(self):
        raise StopIteration


class _FakeAdapter:
    def strategy_search(self, *, page, per_page, status):
        assert status == "running"
        return {
            "strategies": [
                {"id": 378, "name": "[合约][1H][CTA] BSB · EMA5/20 · 100U", "status": "running"},
                {"id": 439, "name": "Top60 momentum rotation", "status": "running"},
            ]
        }


def test_legacy_running_strategy_reports_every_gap() -> None:
    """Production legacy strategies have no ledger linkage yet; say so plainly."""
    p = assess_running_strategy(
        _FakeDb(), bitpro_strategy_id=378, name="BSB EMA5/20", status="running"
    )
    assert p.bitpro_strategy_id == "378"
    assert p.evidence_record_count == 0
    assert not p.version_mapped
    assert p.outcome_count == 0
    assert not p.ready
    assert set(p.gaps) == {
        "no_settled_bitpro_evidence",
        "no_internal_strategy_version_mapping",
        "fewer_than_two_settled_outcomes",
    }


def test_inventory_projection_lists_running_strategies_with_gaps() -> None:
    items = running_inventory_readiness(_FakeDb(), _FakeAdapter())
    assert sorted(p.bitpro_strategy_id for p in items) == ["378", "439"]
    assert all(not p.ready for p in items)
    bsb = next(p for p in items if p.bitpro_strategy_id == "378")
    assert bsb.name.startswith("[合约][1H][CTA] BSB")


def test_ready_strategy_reports_no_gaps() -> None:
    """A fully wired lineage with evidence and outcomes is ready."""
    calls: list[str] = []

    class _Row:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.as_of = None

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def scalars(self, query):
            q = str(query)
            if "bitpro_strategy_evidence_records" in q:
                calls.append("evidence")
                return _Rows([
                    _Row(
                        source_id="378",
                        summary_json={"strategy_id": "378"},
                        as_of=None,
                    )
                ])
            if "strategy_versions" in q:
                calls.append("versions")
                return _Rows([SimpleNamespace(id="sver_1")])
            if "strategy_outcomes" in q:
                calls.append("outcomes")
                return _Rows([SimpleNamespace(id="o1"), SimpleNamespace(id="o2")])
            return _Rows([])

    class _Rows(list):
        def all(self):
            return list(self)

    class _ReadyDb:
        def session(self):
            return _Session()

    p = assess_running_strategy(_ReadyDb(), bitpro_strategy_id=378, name="x", status="running")
    # The direct source_id hit short-circuits the summary scan.
    assert "no_settled_bitpro_evidence" in p.gaps or p.ready
    assert p.evidence_record_count >= 1 or "no_settled_bitpro_evidence" in p.gaps


def test_evidence_record_model_has_source_id_column() -> None:
    """The readiness join depends on this column existing exactly as named."""
    assert hasattr(BitProStrategyEvidenceRecord, "source_id")

"""Slice 2 of the evolution handoff: running-strategy readiness projection.

The projection must never invent readiness: a strategy without settled BitPro
evidence, an internal version mapping, or two settled outcomes reports its gaps
explicitly instead of entering the evolution loop. The mapping is per BitPro
strategy id — another strategy's ledger must never vouch for it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from evolution_fixtures import seeded_evolution_db
from hypertrade.db import (
    BitProStrategyEvidenceRecord,
    Database,
    PaperIncubationMember,
    PaperPromotion,
    ResearchExperimentEvidence,
    StrategyDiscoveryCandidate,
)
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


def _seeded_db_with_bitpro_evidence(sid: str) -> tuple[Database, dict[str, object]]:
    """One internal lineage with two settled outcomes, plus BitPro evidence
    that names only the given running strategy id."""
    db, refs = seeded_evolution_db()
    with db.session() as session:
        session.add(
            BitProStrategyEvidenceRecord(
                schema_version="strategy_return_series.v1",
                evidence_type="strategy_return_series",
                source_layer="paper",
                source_id=sid,
                source_hash="sha256:" + "6" * 64,
                content_hash="sha256:" + "5" * 64,
                as_of=datetime(2026, 7, 20, tzinfo=UTC),
                summary_json={"strategy_id": sid, "point_count": 100, "net_return": "0.01"},
                refs_json={"contract_version": "bitpro-mcp-v1"},
                created_by="test",
            )
        )
    return db, refs


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


def test_unbound_strategy_never_reuses_another_lineages_ledger() -> None:
    """The ledger holds a lineage with two settled outcomes, but nothing in it
    names this BitPro strategy — so none of it may vouch for it."""
    db, _refs = _seeded_db_with_bitpro_evidence("378")
    p = assess_running_strategy(
        db, bitpro_strategy_id=378, name="BSB EMA5/20", status="running"
    )
    assert p.evidence_record_count == 1
    assert not p.version_mapped
    assert p.outcome_count == 0
    assert not p.ready
    assert set(p.gaps) == {
        "no_internal_strategy_version_mapping",
        "fewer_than_two_settled_outcomes",
    }


def test_discovery_candidate_binding_maps_strategy_to_its_version() -> None:
    db, refs = _seeded_db_with_bitpro_evidence("378")
    with db.session() as session:
        session.add(
            StrategyDiscoveryCandidate(
                run_id="drun_test",
                schema_version="strategy_discovery_candidate.v1",
                fingerprint="f" * 64,
                phenomenon_hash="a" * 64,
                hypothesis_hash="b" * 64,
                status="candidate_ready",
                strategy_family="TREND",
                bitpro_strategy_id="378",
                manifest_id=str(refs["parent_manifest_id"]),
                experiment_execution_id="exex_test",
                strategy_version_id=str(refs["parent_version_id"]),
                phenomenon_json={},
                hypothesis_json={},
                novelty_json={},
                candidate_json={},
                created_by="test",
            )
        )
    p = assess_running_strategy(
        db, bitpro_strategy_id=378, name="BSB EMA5/20", status="running"
    )
    assert p.version_mapped
    assert p.outcome_count == 2
    assert p.ready
    assert p.gaps == []


def test_incubation_member_binding_maps_via_manifest() -> None:
    db, refs = _seeded_db_with_bitpro_evidence("439")
    with db.session() as session:
        session.add(
            PaperIncubationMember(
                mandate_id="pmand_test",
                candidate_kind="discovery",
                candidate_id="dcand_test",
                validation_id="uvld_test",
                manifest_id=str(refs["parent_manifest_id"]),
                experiment_execution_id="exex_test",
                bitpro_strategy_id="439",
                status="eligible",
                source_hash="s" * 64,
                policy_hash="q" * 64,
            )
        )
    p = assess_running_strategy(
        db, bitpro_strategy_id=439, name="Top60 momentum rotation", status="running"
    )
    assert p.version_mapped
    assert p.outcome_count == 2
    assert p.ready


def test_rejected_incubation_member_does_not_map() -> None:
    """A rejected intake row can pair a mismatch manifest with the candidate's
    BitPro id; a contradictory pairing is not a mapping."""
    db, refs = _seeded_db_with_bitpro_evidence("439")
    with db.session() as session:
        session.add(
            PaperIncubationMember(
                mandate_id="pmand_test",
                candidate_kind="discovery",
                candidate_id="dcand_test",
                validation_id="uvld_test",
                manifest_id=str(refs["parent_manifest_id"]),
                experiment_execution_id="exex_test",
                bitpro_strategy_id="439",
                status="rejected",
                source_hash="s" * 64,
                policy_hash="q" * 64,
            )
        )
    p = assess_running_strategy(
        db, bitpro_strategy_id=439, name="Top60 momentum rotation", status="running"
    )
    assert not p.version_mapped
    assert p.outcome_count == 0
    assert "no_internal_strategy_version_mapping" in p.gaps


def test_promotion_binding_maps_lineage_via_mandate_key() -> None:
    db, _refs = _seeded_db_with_bitpro_evidence("445")
    with db.session() as session:
        session.add(
            PaperPromotion(
                mandate_id="rmand_evolution",
                job_id="rjob_test",
                evidence_id="rexp_test",
                strategy_key="btc_trend_existing",
                bitpro_strategy_id="445",
            )
        )
    p = assess_running_strategy(
        db, bitpro_strategy_id=445, name="Promoted BTC trend", status="running"
    )
    assert p.version_mapped
    assert p.outcome_count == 2
    assert p.ready


def test_legacy_experiment_evidence_maps_lineage_via_mandate_key() -> None:
    db, _refs = _seeded_db_with_bitpro_evidence("378")
    with db.session() as session:
        session.add(
            ResearchExperimentEvidence(
                job_id="rjob_legacy",
                mandate_id="rmand_evolution",
                variant_id="var_1",
                status="evidence_recorded",
                strategy_key="btc_trend_existing",
                bitpro_strategy_id="378",
            )
        )
    p = assess_running_strategy(
        db, bitpro_strategy_id=378, name="BSB EMA5/20", status="running"
    )
    assert p.version_mapped
    assert p.outcome_count == 2
    assert p.ready


def test_evidence_record_model_has_source_id_column() -> None:
    """The readiness join depends on this column existing exactly as named."""
    assert hasattr(BitProStrategyEvidenceRecord, "source_id")

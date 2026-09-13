"""Immutable, read-only sleeve-index research. No allocation or execution authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import JSON, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from hypertrade.bitpro.strategy_evidence import validate_return_series
from hypertrade.db import Base, Database


class PortfolioResearchRecord(Base):
    __tablename__ = "portfolio_research_records"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(128))


class PortfolioMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_layer: Literal["backtest", "paper"]
    source_id: str = Field(min_length=1, max_length=128)
    weight: Decimal = Field(ge=0, allow_inf_nan=False, max_digits=30, decimal_places=18)
    # This describes the source strategy, never a request to invert its net PnL.
    direction: Literal["long", "short", "both"]


class PortfolioFreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    members: tuple[PortfolioMemberRequest, ...] = Field(max_length=20)
    cash_weight: Decimal = Field(
        default=Decimal(0), ge=0, allow_inf_nan=False, max_digits=30, decimal_places=18
    )
    start_at: datetime
    end_at: datetime
    bucket_seconds: Literal[3600, 14400, 86400] = 3600
    initial_capital: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=30, decimal_places=18)
    currency: Literal["USDT"] = "USDT"
    rebalance_at: tuple[datetime, ...] = ()
    rebalance_fee_bps: Decimal = Field(
        ge=0, le=100, allow_inf_nan=False, max_digits=30, decimal_places=18
    )
    rebalance_slippage_bps: Decimal = Field(
        ge=0, le=100, allow_inf_nan=False, max_digits=30, decimal_places=18
    )

    @field_validator("start_at", "end_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return utc(value)

    @field_validator("rebalance_at")
    @classmethod
    def aware_schedule(cls, values: tuple[datetime, ...]) -> tuple[datetime, ...]:
        return tuple(sorted(utc(v) for v in values))

    @model_validator(mode="after")
    def bounds(self) -> PortfolioFreezeRequest:
        intervals = (self.end_at - self.start_at).total_seconds() / self.bucket_seconds
        if not 1 <= intervals <= 499 or intervals != int(intervals):
            raise ValueError("window must contain 1..499 complete buckets")
        if self.end_at > datetime.now(UTC):
            raise ValueError("window must be historical")
        if self.start_at.timestamp() % self.bucket_seconds:
            raise ValueError("window must align to UTC buckets")
        ids = [(m.source_layer, m.source_id) for m in self.members]
        if len(set(ids)) != len(ids) or len({m.source_layer for m in self.members}) > 1:
            raise ValueError("unique members from one source layer required")
        if sum((m.weight for m in self.members), self.cash_weight) <= 0:
            raise ValueError("positive total weight required")
        if len(set(self.rebalance_at)) != len(self.rebalance_at):
            raise ValueError("duplicate rebalance boundary")
        for t in self.rebalance_at:
            if not self.start_at < t < self.end_at or t.timestamp() % self.bucket_seconds:
                raise ValueError("rebalance must be an interior UTC bucket boundary")
        return self


class PortfolioReadAdapter(Protocol):
    def strategy_return_series(self, **parameters: Any) -> dict[str, Any]: ...


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value.astimezone(UTC)


def canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return canonical(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("finite amount required")
        # Do not normalize under the caller's Decimal context (it can round hashes).
        return (
            format(value, "f").rstrip("0").rstrip(".")
            if "." in format(value, "f")
            else format(value, "f")
        )
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            canonical(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def normalized_request(request: PortfolioFreezeRequest) -> dict[str, Any]:
    with localcontext() as ctx:
        ctx.prec = 60
        values = sorted(request.members, key=lambda m: (m.source_layer, m.source_id))
        total = sum((m.weight for m in values), request.cash_weight)
        # Fixed 18-place normalization, with residual assigned to cash; no hidden leverage.
        weights = [
            (m.weight / total).quantize(Decimal("1e-18"), rounding="ROUND_DOWN") for m in values
        ]
        result = request.model_dump(mode="python")
        result["members"] = [
            {**m.model_dump(), "weight": w} for m, w in zip(values, weights, strict=True)
        ]
        result["cash_weight"] = 1 - sum(weights)
        return cast(dict[str, Any], canonical(result))


class PortfolioResearchService:
    def __init__(self, db: Database, reader: PortfolioReadAdapter) -> None:
        self.db, self.reader = db, reader

    def get(self, record_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(PortfolioResearchRecord, record_id)
            if row is None:
                raise KeyError(record_id)
            payload = dict(row.payload)
        if record_id != payload.get("id") or record_id.split("_", 1)[1] != digest(
            {k: v for k, v in payload.items() if k != "id"}
        ):
            raise ValueError("portfolio_ledger_integrity_failure")
        return payload

    def _save(self, payload: dict[str, Any], *, prefix: str, actor: str) -> dict[str, Any]:
        value = canonical(payload)
        record_id = prefix + "_" + digest(value)
        value = {"id": record_id, **value}
        # Content addressing + primary key resolves concurrent capture and crash replay.
        with self.db.session() as session:
            session.add(PortfolioResearchRecord(id=record_id, payload=value, actor=actor))
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return self.get(record_id)
        return value

    def _collect(self, request: PortfolioFreezeRequest) -> list[dict[str, Any]]:
        pages = []
        expected = [
            request.start_at + timedelta(seconds=i * request.bucket_seconds)
            for i in range(
                int((request.end_at - request.start_at).total_seconds()) // request.bucket_seconds
                + 1
            )
        ]
        for member in sorted(request.members, key=lambda m: (m.source_layer, m.source_id)):
            page = validate_return_series(
                self.reader.strategy_return_series(
                    source_layer=member.source_layer,
                    source_id=member.source_id,
                    start_at=request.start_at.isoformat(),
                    end_at=request.end_at.isoformat(),
                    bucket_seconds=request.bucket_seconds,
                    limit=500,
                )
            )
            if (
                page["source_layer"] != member.source_layer
                or page["source_id"] != member.source_id
                or page["currency"] != request.currency
                or page["bucket_seconds"] != request.bucket_seconds
                or page["pagination"]["cursor"]
                or page["pagination"]["next_cursor"]
                or set(page["data_gaps"]) - {"gross_return_unavailable"}
            ):
                raise ValueError("incomplete_or_mismatched_member")
            times = [
                utc(datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")))
                for p in page["points"]
            ]
            if times != expected or any(Decimal(p["equity"]) <= 0 for p in page["points"]):
                raise ValueError("incomplete_coverage_or_nonpositive_equity")
            if len(page["symbols"]) != 1:
                raise ValueError("multi_asset_member_contribution_unavailable")
            if not page["strategy_version"] or not page["config_version"] or not page["timeframe"]:
                raise ValueError("member_version_unavailable")
            pages.append(page)
        if len({digest(cost_policy(p)) for p in pages}) > 1:
            raise ValueError("incompatible_member_costs")
        return pages

    def freeze(self, request: PortfolioFreezeRequest, *, actor: str) -> dict[str, Any]:
        try:
            pages = self._collect(request)
        except Exception as exc:
            return unavailable(exc)
        spec = normalized_request(request)
        with localcontext() as ctx:
            ctx.prec = 60
            baseline_weights = ([Decimal(1) / len(pages)] * len(pages)) if pages else []
        manifest = {
            "schema_version": "portfolio_manifest.v1",
            "engine_version": "sleeve_index.v1",
            "identity_semantics": "observed_source_identity",
            "request": spec,
            "members": [
                {**member, **identity(page)}
                for member, page in zip(spec["members"], pages, strict=True)
            ],
            "portfolio_cost_policy": {
                "model": "proportional_reallocation.v1",
                "fee_bps": spec["rebalance_fee_bps"],
                "slippage_bps": spec["rebalance_slippage_bps"],
                "member_costs": "embedded_in_source_net_equity",
                "terminal_liquidation": False,
            },
            "rebalance_timing": "after_close_affects_next_interval",
            "measurement": "hypothetical_scaled_net_sleeve_indices",
            "baseline_policy": "equal_weight_buy_and_hold.v1",
            "baseline": {
                "weights": baseline_weights,
                "rebalance_at": [],
                "members": [identity(p) for p in pages],
            },
        }
        return self._save(
            {"status": "frozen", "manifest": manifest, "execution_authorized": False},
            prefix="pm",
            actor=actor,
        )

    def compare(self, manifest_id: str, *, actor: str) -> dict[str, Any]:
        frozen = self.get(manifest_id)
        if frozen.get("status") != "frozen":
            raise ValueError("manifest record required")
        manifest = frozen["manifest"]
        request = PortfolioFreezeRequest.model_validate(manifest["request"])
        try:
            pages = self._collect(request)
            if [identity(p) for p in pages] != [
                {k: m[k] for k in identity(p)}
                for m, p in zip(manifest["members"], pages, strict=True)
            ]:
                raise ValueError("member_version_or_output_drift")
        except Exception as exc:
            return {
                **unavailable(exc),
                "manifest_id": manifest_id,
                "candidate": None,
                "baseline": None,
            }
        with localcontext() as ctx:
            ctx.prec = 60
            weights = [Decimal(m["weight"]) for m in manifest["members"]]
            candidate = replay(request, pages, weights, request.rebalance_at)
            baseline_weights = [Decimal(w) for w in manifest["baseline"]["weights"]]
            baseline = replay(request, pages, baseline_weights, ())
            return_delta = Decimal(candidate["net_return"]) - Decimal(baseline["net_return"])
        baseline["policy"] = "equal_weight_buy_and_hold.v1"
        gaps = ["member_fee_breakdown_unavailable", "member_turnover_unavailable"] if pages else []
        if any(m.source_layer == "backtest" for m in request.members):
            gaps.append("member_run_provenance_unverified")
        result = canonical(
            {
                "schema_version": "portfolio_comparison.v1",
                "manifest_id": manifest_id,
                "status": "needs_data" if gaps else "available",
                "data_gaps": gaps,
                "candidate": candidate,
                "baseline": baseline,
                "recommendation": "collect_evidence" if gaps else "no_change",
                "execution_authorized": False,
                "allocation_authorized": False,
                "return_delta": return_delta,
            }
        )
        # Persist summaries and curve digests only, following the existing portfolio data plane.
        summary = {
            **result,
            "candidate": {k: v for k, v in result["candidate"].items() if k != "equity_curve"},
            "baseline": {k: v for k, v in result["baseline"].items() if k != "equity_curve"},
        }
        saved = self._save(summary, prefix="pc", actor=actor)
        return {"id": saved["id"], **result}


def cost_policy(page: dict[str, Any]) -> dict[str, Any]:
    # Realized funding totals belong to each source, not the comparable rate identity.
    costs = page["cost_model"]
    for section, allowed in (
        ("fees", {"maker_fee_bps", "taker_fee_bps", "commission_rate"}),
        ("slippage", {"slippage_bps", "slippage_rate"}),
    ):
        if set(costs[section]) - allowed:
            raise ValueError("unsupported_cost_metadata")
        for value in costs[section].values():
            if value is not None and (
                isinstance(value, bool)
                or not Decimal(str(value)).is_finite()
                or Decimal(str(value)) < 0
            ):
                raise ValueError("invalid_member_cost")
    if set(costs["funding"]) - {"mode", "total_fee"}:
        raise ValueError("unsupported_cost_metadata")
    if costs["funding"]["mode"] not in {
        "included",
        "excluded",
        "unavailable",
        "not_modeled",
        "strategy_defined_or_not_modeled",
    }:
        raise ValueError("unsupported_funding_mode")
    return {
        "fees": costs["fees"],
        "slippage": costs["slippage"],
        "funding": {"mode": costs["funding"]["mode"]},
    }


def identity(page: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "strategy_id",
        "strategy_version",
        "config_version",
        "symbols",
        "timeframe",
        "currency",
        "source_hash",
        "content_hash",
    )
    return {
        **{k: page[k] for k in keys},
        "cost_policy_hash": digest(cost_policy(page)),
        "instrument_version": digest(
            {"symbols": page["symbols"], "config_version": page["config_version"]}
        ),
        "source_cost_model": page["cost_model"],
        "source_window_start_equity": page["points"][0]["equity"],
    }


def unavailable(exc: Exception) -> dict[str, Any]:
    # Exceptions can contain transport URLs or auth material; persist only public reason codes.
    reason = (
        str(exc)
        if isinstance(exc, ValueError)
        and str(exc)
        in {
            "incomplete_or_mismatched_member",
            "incomplete_coverage_or_nonpositive_equity",
            "multi_asset_member_contribution_unavailable",
            "member_version_unavailable",
            "incompatible_member_costs",
            "member_version_or_output_drift",
        }
        else "member_evidence_unavailable"
    )
    return {
        "status": "needs_data",
        "data_gaps": [reason],
        "execution_authorized": False,
        "allocation_authorized": False,
        "recommendation": "collect_evidence",
    }


def rebalance(
    values: list[Decimal], cash: Decimal, weights: list[Decimal], rate: Decimal
) -> tuple[list[Decimal], Decimal, Decimal, Decimal]:
    equity = sum(values, cash)
    # Solve E_after = E_before - rate * sum(abs(weight * E_after - holding)).
    # Fees are funded by the portfolio, so a fully invested portfolio cannot create cash.
    low, high = Decimal(0), equity
    for _ in range(180):
        post = (low + high) / 2
        cost = (
            sum((abs(w * post - v) for w, v in zip(weights, values, strict=True)), Decimal(0))
            * rate
        )
        if post + cost > equity:
            high = post
        else:
            low = post
    post = (low + high) / 2
    targets = [w * post for w in weights]
    turnover = sum((abs(t - v) for t, v in zip(targets, values, strict=True)), Decimal(0))
    fees = turnover * rate
    cash = equity - fees - sum(targets)
    return targets, cash, turnover, fees


def replay(
    request: PortfolioFreezeRequest,
    pages: list[dict[str, Any]],
    weights: list[Decimal],
    schedule: tuple[datetime, ...],
) -> dict[str, Any]:
    capital = request.initial_capital
    rate = (request.rebalance_fee_bps + request.rebalance_slippage_bps) / 10000
    values, cash, turnover, fees = rebalance([Decimal(0)] * len(pages), capital, weights, rate)
    pnl = [Decimal(0)] * len(pages)
    peak, drawdown = capital, Decimal(0)
    curve = []
    count = int((request.end_at - request.start_at).total_seconds()) // request.bucket_seconds + 1
    for i in range(count):
        t = request.start_at + timedelta(seconds=i * request.bucket_seconds)
        if i:
            for j, page in enumerate(pages):
                gain = values[j] * (
                    Decimal(page["points"][i]["equity"]) / Decimal(page["points"][i - 1]["equity"])
                    - 1
                )
                values[j] += gain
                pnl[j] += gain
            if t in schedule:
                values, cash, traded, paid = rebalance(values, cash, weights, rate)
                turnover += traded
                fees += paid
        equity = sum(values, cash)
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        curve.append({"timestamp": t, "equity": equity})
    assets: dict[str, Decimal] = {}
    for page, amount in zip(pages, pnl, strict=True):
        symbol = page["symbols"][0]
        assets[symbol] = assets.get(symbol, Decimal(0)) + amount
    return cast(
        dict[str, Any],
        canonical(
            {
                "asset_contributions": [
                    {"symbol": k, "net_pnl": v} for k, v in sorted(assets.items())
                ],
                "ending_equity": equity,
                "net_return": equity / capital - 1,
                "max_drawdown": drawdown,
                "equity_curve": curve,
                "curve_hash": digest(curve),
                "rebalance_turnover": turnover,
                "rebalance_fees": fees,
                "fees": None if pages else Decimal(0),
                "turnover": None if pages else Decimal(0),
                "contributions": [
                    {"source_id": p["source_id"], "symbol": p["symbols"][0], "net_pnl": v}
                    for p, v in zip(pages, pnl, strict=True)
                ],
                "measurement": "sampled_sleeve_index_net_of_modeled_reallocation_costs",
                "capital_scaling": "linear_hypothesis_not_executable_strategy_replay",
            }
        ),
    )

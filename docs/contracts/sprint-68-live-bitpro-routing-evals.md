# Sprint 68 - Live BitPro Routing Evals

## Goal

Promote recent live BitPro routing regressions into the deterministic Agent eval
suite so production operators can see when live account prompts accidentally
fall back to generic market reports.

## In Scope

- Add an eval case for `我的实盘最近的一笔订单是什么`.
- Add an eval case for `看下实盘收益最高的策略`.
- Require the matching BitPro live diagnostic tools and forbid `market_summary`.
- Add default deterministic observations with source ids, without calling live
  BitPro or exchange services.
- Update API/test/docs expectations for `/evals`.

## Out of Scope

- Adding model-judge evals or paid external eval services.
- Changing BitPro live read tools or report rendering.
- Running live-write, order placement, cancellation, transfer, or promotion
  tools.

## Done Means

- `/evals` includes `live_order_history_source` and
  `live_strategy_performance_source`.
- Both cases fail when the observation uses `market_summary` or emits
  `Market Report` / `市场热度总结` instead of BitPro evidence.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_agent_eval_suite.py tests/test_api.py -q
./scripts/check.sh
```

import type { HarnessOverview } from "../types";

/**
 * What the console knows before the first overview arrives: nothing. Every count is zero and every
 * list is empty. It exists only so pages that read `overview.x.count` have a number to show; it
 * must never contain an invented provider, tool, price or account.
 */
export const EMPTY_OVERVIEW: HarnessOverview = {
  generated_at: "",
  headless_mode: false,
  missions_summary: {
    total_count: 0,
    active_count: 0,
    completed_count: 0,
    failed_count: 0,
    threads_count: 0
  },
  providers: [],
  tools: [],
  market: { ticker_count: 0, latest_ticker_at: null, latest_update_age_seconds: null, top_movers: [] },
  agent_runs: { total_count: 0, recent: [] },
  rag: { document_count: 0, chunk_count: 0 },
  memory: {
    active_count: 0,
    total_count: 0,
    latest_created_at: null,
    cognitive: {
      episodic_count: 0,
      semantic_count: 0,
      active_semantic_count: 0,
      hypothesis_count: 0
    }
  },
  trace: { total_count: 0, recent_events: [] },
  paper: {
    session: { id: "", status: "unknown", cash: "0", equity: "0", realized_pnl: "0" },
    positions: [],
    recent_fills: [],
    recent_events: []
  },
  strategy_lab: { latest_research: null, latest_backtest: null, latest_experiment: null },
  live_orders: { total_count: 0, pending_approval_count: 0, recent: [] },
  evals: { status: "not_loaded", case_count: 0, mode: "unknown", cases: [] }
};

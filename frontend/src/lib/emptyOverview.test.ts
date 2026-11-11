import { expect, test } from "vitest";
import { EMPTY_OVERVIEW } from "./emptyOverview";

test("the empty overview contains no invented entity, price or account", () => {
  // It replaced a fixture with a fake paper account, fake providers/tools and a BitPro
  // configuration that the page kept showing as if live whenever the API was unreachable.
  expect(EMPTY_OVERVIEW.providers).toEqual([]);
  expect(EMPTY_OVERVIEW.tools).toEqual([]);
  expect(EMPTY_OVERVIEW.bitpro).toBeUndefined();
  expect(EMPTY_OVERVIEW.market.top_movers).toEqual([]);
  expect(EMPTY_OVERVIEW.trace.recent_events).toEqual([]);
  expect(EMPTY_OVERVIEW.agent_runs.recent).toEqual([]);
  expect(EMPTY_OVERVIEW.generated_at).toBe("");
});

test("every count is zero so a page that reads one never shows a made-up number", () => {
  expect(EMPTY_OVERVIEW.market.ticker_count).toBe(0);
  expect(EMPTY_OVERVIEW.agent_runs.total_count).toBe(0);
  expect(EMPTY_OVERVIEW.rag).toEqual({ document_count: 0, chunk_count: 0 });
  expect(EMPTY_OVERVIEW.memory.active_count).toBe(0);
  expect(EMPTY_OVERVIEW.memory.total_count).toBe(0);
  expect(EMPTY_OVERVIEW.trace.total_count).toBe(0);
  expect(EMPTY_OVERVIEW.live_orders.total_count).toBe(0);
  expect(EMPTY_OVERVIEW.paper.session.status).toBe("unknown");
  expect(EMPTY_OVERVIEW.evals.status).toBe("not_loaded");
});

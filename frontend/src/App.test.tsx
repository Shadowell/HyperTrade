import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import App from "./App";

const overview = {
  generated_at: "2026-05-27T00:00:00+08:00",
  providers: [
    {
      name: "deepseek",
      display_name: "DeepSeek",
      model: "deepseek-v4-flash",
      enabled: true,
      default: true,
      key_status: "configured"
    },
    {
      name: "qwen",
      display_name: "Qwen",
      model: "text-embedding-v4",
      enabled: true,
      default: false,
      key_status: "configured"
    }
  ],
  tools: [
    {
      name: "market.summary",
      description: "Summarize OKX SWAP market state.",
      category: "market",
      requires_approval: false
    },
    {
      name: "live.order_intent",
      description: "Create a live/testnet order intent.",
      category: "live",
      requires_approval: true
    }
  ],
  market: {
    ticker_count: 344,
    latest_ticker_at: "2026-05-27T00:00:00+08:00",
    latest_update_age_seconds: 42,
    top_movers: [
      {
        inst_id: "BTC-USDT-SWAP",
        last: "70000",
        volume_ccy_24h: "20000",
        change_utc0_pct: "4.2"
      }
    ]
  },
  agent_runs: {
    total_count: 1,
    recent: [
      {
        id: "run_live",
        prompt: "请做行情归纳",
        status: "completed",
        created_at: "2026-05-27T00:00:00+08:00",
        updated_at: "2026-05-27T00:00:00+08:00",
        error: ""
      }
    ]
  },
  rag: {
    document_count: 2,
    chunk_count: 5
  },
  memory: {
    active_count: 1,
    total_count: 1,
    latest_created_at: "2026-05-27T00:00:00+08:00"
  },
  trace: {
    total_count: 3,
    recent_events: [
      {
        id: "evt_1",
        tool_name: "market.summary",
        status: "completed",
        created_at: "2026-05-27T00:00:00+08:00"
      }
    ]
  }
};

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders harness observability from live overview", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ username: "admin" });
      }
      if (url.endsWith("/api/harness/overview")) {
        return jsonResponse(overview);
      }
      return jsonResponse({}, 404);
    })
  );

  render(<App />);

  expect(screen.getAllByText("Harness").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("行情摘要").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Tool Call Trace")).toBeInTheDocument();
  expect(screen.getAllByText("OKX SWAP").length).toBeGreaterThanOrEqual(1);
  expect(await screen.findByText("344")).toBeInTheDocument();
  expect(screen.getAllByText("DeepSeek / deepseek-v4-flash").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("run_live")).toBeInTheDocument();
  expect(screen.getByText("BTC-USDT-SWAP")).toBeInTheDocument();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body
  } as Response;
}

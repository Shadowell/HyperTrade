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
  },
  paper: {
    session: {
      id: "paper_live",
      status: "running",
      cash: "100000",
      equity: "100000",
      realized_pnl: "0"
    },
    positions: [
      {
        inst_id: "AAA-USDT-SWAP",
        side: "long",
        quantity: "99.98",
        entry_price: "10.002",
        mark_price: "10.002",
        notional: "1000",
        unrealized_pnl: "0"
      }
    ],
    recent_fills: [
      {
        inst_id: "AAA-USDT-SWAP",
        side: "long",
        quantity: "99.98",
        price: "10.002",
        fee: "0.5",
        created_at: "2026-05-27T00:00:00+08:00"
      }
    ],
    recent_events: []
  },
  strategy_lab: {
    latest_research: {
      id: "srch_live",
      prompt: "研究一个趋势突破策略",
      strategy_key: "momentum_breakout_v1",
      title: "趋势突破 V1",
      report_markdown: "# 趋势突破 V1",
      spec_json: {},
      created_at: "2026-05-27T00:00:00+08:00"
    },
    latest_backtest: {
      id: "bt_live",
      research_id: "srch_live",
      strategy_key: "momentum_breakout_v1",
      status: "completed",
      metrics: {
        start_cash: "100000",
        end_value: "100014",
        total_return_pct: "0.014000",
        max_drawdown_pct: "0",
        trade_count: 1
      },
      report_markdown: "# Backtest Report",
      report_json: {},
      created_at: "2026-05-27T00:00:00+08:00"
    }
  },
  live_orders: {
    total_count: 1,
    pending_approval_count: 1,
    recent: [
      {
        id: "loi_live",
        environment: "testnet",
        status: "pending_approval",
        inst_id: "ETH-USDT-SWAP",
        side: "buy",
        order_type: "market",
        size: "0.01",
        price: null,
        reason: "fixture",
        decision_reason: "",
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
      if (url.endsWith("/api/memory")) {
        return jsonResponse({
          items: [
            {
              id: "mem_live",
              kind: "agent_note",
              content: "**ETH** trend reviewed",
              source_run_id: "run_live",
              source_tool: "memory.write",
              created_at: "2026-05-27T00:00:00+08:00"
            }
          ]
        });
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
  expect(screen.getAllByText("run_live").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("BTC-USDT-SWAP")).toBeInTheDocument();
  expect(screen.getByText("Paper Runtime")).toBeInTheDocument();
  expect(screen.getAllByText("running").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("AAA-USDT-SWAP").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Strategy Lab")).toBeInTheDocument();
  expect(screen.getByText("momentum_breakout_v1")).toBeInTheDocument();
  expect(screen.getByText("bt_live")).toBeInTheDocument();
  expect(screen.getByText("0.014000%")).toBeInTheDocument();
  expect(screen.getByText("Live Approval")).toBeInTheDocument();
  expect(screen.getByText("loi_live")).toBeInTheDocument();
  expect(screen.getByText("ETH-USDT-SWAP buy 0.01")).toBeInTheDocument();
  expect(screen.getByText("行情工具")).toBeInTheDocument();
  expect(screen.getByText("Memory 管理")).toBeInTheDocument();
  expect((await screen.findAllByText("mem_live")).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("报告阅读")).toBeInTheDocument();
  expect(screen.getByText("完整回测")).toBeInTheDocument();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body
  } as Response;
}

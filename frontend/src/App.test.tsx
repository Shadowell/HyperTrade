import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
    },
    latest_experiment: {
      id: "exp_live",
      prompt: "研究ETH趋势突破",
      status: "completed",
      research_id: "srch_live",
      backtest_id: "bt_live",
      report_markdown: "# Experiment",
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
        risk_status: "allowed",
        exchange_order_id: "",
        created_at: "2026-05-27T00:00:00+08:00"
      }
    ]
  },
  bitpro: {
    adapter: "mcp_non_live_lifecycle",
    configured: true,
    api_base: "http://127.0.0.1:8889/api/v2",
    auth_header: "X-BitPro-MCP-Token",
    token_configured: true,
    token_source: "bitpro_settings_agent_token_or_server_env",
    remote_mcp: {
      transport: "streamable-http",
      path_default: "/api/v2/mcp/",
      auth_header_default: "X-BitPro-MCP-Token",
      token_env: "BITPRO_MCP_API_TOKEN",
      token_status_path: "/settings/mcp-token",
      token_generate_path: "/settings/mcp-token/generate"
    },
    agent_auth: {
      auth_header_default: "X-BitPro-MCP-Token",
      static_token_env: "BITPRO_MCP_API_TOKEN",
      token_management: {
        settings_routes: {
          list: "GET /api/v2/settings/mcp-agent-tokens",
          create: "POST /api/v2/settings/mcp-agent-tokens",
          revoke: "DELETE /api/v2/settings/mcp-agent-tokens/{token_id}"
        },
        plaintext_returned_once: true,
        default_tool_groups: ["read", "research_backtest_paper_mutation", "live_diagnostic"]
      },
      scope_classes: {
        R: { label: "read", tool_group: "read" },
        W: { label: "research_backtest_paper_mutation", tool_group: "research_backtest_paper_mutation" },
        L: { label: "live_diagnostic", tool_group: "live_diagnostic" },
        T: { label: "live_mutation", tool_group: "live_mutation" }
      },
      idempotency: {
        required_tools: ["backtest_start_job", "paper_start"]
      }
    },
    tool_groups: {
      read: ["bitpro_capabilities", "bitpro_health", "market_klines"],
      research_backtest_paper_mutation: ["strategy_create", "backtest_start_job", "paper_start"],
      live_diagnostic: ["live_preflight", "trading_positions"],
      live_mutation: ["trading_futures_order"]
    },
    live_write_enabled: false,
    live_write_scope: "hypertrade_mcp_live_write_gate",
    tools: [
      "bitpro_capabilities",
      "bitpro_health",
      "market_klines",
      "strategy_generate",
      "strategy_create",
      "backtest_start_job",
      "paper_configure",
      "paper_start",
      "paper_dashboard",
      "trading_positions"
    ]
  },
  evals: {
    status: "passed",
    case_count: 5,
    mode: "deterministic",
    cases: [
      { name: "tool_selection", status: "passed" },
      { name: "rag_citation", status: "passed" }
    ]
  }
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("renders harness observability from live overview", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
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
            tags: ["agent_note"],
            usage_count: 1,
            created_at: "2026-05-27T00:00:00+08:00"
          }
        ]
      });
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(screen.getAllByText("工作台").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("工具调用链路")).toBeInTheDocument();
  expect(screen.getAllByText("OKX SWAP").length).toBeGreaterThanOrEqual(1);
  expect(await screen.findByText("344")).toBeInTheDocument();
  expect(screen.getAllByText("DeepSeek / deepseek-v4-flash").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("run_live").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("BTC-USDT-SWAP")).toBeInTheDocument();
  expect(screen.getByText("记忆管理")).toBeInTheDocument();
  expect((await screen.findAllByText("mem_live")).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("报告阅读")).toBeInTheDocument();
  expect(screen.getByText("异动榜")).toBeInTheDocument();
  expect(screen.getAllByText("最近运行").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("BitPro MCP 接入")).toBeInTheDocument();
  expect(screen.getByText("BitPro 设置 / 服务器环境")).toBeInTheDocument();
  expect(screen.getAllByText("X-BitPro-MCP-Token").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("R / W / L / T")).toBeInTheDocument();
  expect(screen.queryByText("模拟盘运行")).not.toBeInTheDocument();
  expect(screen.queryByText("策略实验室")).not.toBeInTheDocument();
  expect(screen.queryByText("实盘审批")).not.toBeInTheDocument();
  expect(screen.queryByText("行情工具")).not.toBeInTheDocument();
  expect(screen.queryByText("智能体评测")).not.toBeInTheDocument();
  expect(screen.queryByText("完整回测")).not.toBeInTheDocument();
  expect(screen.queryByText("转发飞书")).not.toBeInTheDocument();
  expect(screen.queryByText("禁用")).not.toBeInTheDocument();
  expect(screen.queryByText("Tool Call Trace")).not.toBeInTheDocument();
  expect(screen.queryByText("Paper Runtime")).not.toBeInTheDocument();
  expect(screen.queryByText("Strategy Lab")).not.toBeInTheDocument();
  expect(screen.queryByText("Live Approval")).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalledWith("/api/auth/me", expect.anything());
  expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "登录" })).not.toBeInTheDocument();
});

test("sidebar navigation keeps the clicked section active", async () => {
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
        return jsonResponse({ items: [] });
      }
      return jsonResponse({}, 404);
    })
  );

  render(<App />);

  const harnessLink = screen.getByRole("link", { name: "工作台" });
  const runsLink = screen.getByRole("link", { name: "最近运行" });
  expect(harnessLink).toHaveClass("nav-item-active");

  fireEvent.click(runsLink);

  expect(runsLink).toHaveClass("nav-item-active");
  expect(harnessLink).not.toHaveClass("nav-item-active");
  expect(await screen.findByText("344")).toBeInTheDocument();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body
  } as Response;
}

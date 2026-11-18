import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import App from "./App";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function sseResponse(events: Array<{ seq: number; type: string; payload?: Record<string, unknown> }>) {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const evt of events) {
        controller.enqueue(
          encoder.encode(
            `id: ${evt.seq}\nevent: ${evt.type}\ndata: ${JSON.stringify({
              event_id: `evt_${evt.seq}`,
              event_type: evt.type,
              thread_sequence: evt.seq,
              payload: evt.payload ?? {}
            })}\n\n`
          )
        );
      }
      controller.close();
    }
  });
  return new Response(body, { status: 200 });
}

function makeOverview(overrides: Record<string, unknown> = {}) {
  return {
    generated_at: "2026-11-18T10:30:00+08:00",
    headless_mode: true,
    providers: [
      {
        name: "deepseek",
        display_name: "DeepSeek",
        model: "deepseek-reasoner",
        enabled: true,
        default: true,
        key_status: "configured"
      }
    ],
    tools: [
      {
        name: "bitpro_paper_dashboard",
        description: "Inspect BitPro Paper state",
        category: "bitpro",
        requires_approval: false
      }
    ],
    agent_runs: {
      total_count: 2,
      recent: [
        {
          id: "mis_recent_1",
          prompt: "诊断 3-Slot 进化预算与赛马表现",
          status: "completed",
          created_at: "2026-11-18T09:00:00+08:00",
          updated_at: "2026-11-18T09:02:00+08:00",
          error: ""
        }
      ]
    },
    missions_summary: {
      total_count: 5,
      active_count: 1,
      threads_count: 3
    },
    rag: {
      document_count: 4,
      chunk_count: 19
    },
    memory: {
      active_count: 12,
      total_count: 15,
      latest_created_at: "2026-11-18T08:00:00+08:00",
      cognitive: {
        active_semantic_count: 4,
        superseded_semantic_count: 1,
        episodic_count: 7,
        hypothesis_count: 3
      }
    },
    trace: {
      total_count: 9,
      recent_events: [
        {
          id: "evt_bp",
          tool_name: "bitpro_paper_dashboard",
          status: "completed",
          output_json: { running_bots: 3 }
        }
      ]
    },
    bitpro: {
      configured: true,
      adapter_mode: "mcp",
      api_base: "https://bitpro.notenap.com/mcp",
      token_configured: true,
      live_write_enabled: false,
      auth_header: "Authorization: Bearer",
      scope_groups: ["paper:read", "evolution:read"],
      tools: ["bitpro_paper_dashboard", "bitpro_backtest_matrix"],
      live_probe: {
        status: "online",
        reachable: true,
        authenticated: true,
        latency_ms: 42,
        tool_count: 24,
        hint: ""
      }
    },
    evals: {
      status: "passed",
      case_count: 28,
      research_os: { status: "passed" },
      quality: { provider_baseline: "deepseek-reasoner", metric_contract: "v2.1" }
    },
    observability: {
      total_tokens: 48200
    },
    ...overrides
  };
}

function makeHealthz() {
  return {
    status: "ok",
    service: "hypertrade-api",
    database: { status: "ok", latency_ms: 6.4 },
    adapters: { bitpro: { status: "ok" }, quantlab: { status: "ok" } },
    workers: {
      status: "alive",
      failing_components: ["ablation_sweep"],
      instances: [
        {
          worker_id: "worker-alpha",
          status: "alive",
          stale: false,
          heartbeat_age_seconds: 4,
          uptime_seconds: 7200,
          stalls_total: 1,
          event_loop_lag_max_seconds: 0.042,
          failing_components: ["ablation_sweep"],
          last_stall: {
            seconds: 18.4,
            age_seconds: 120,
            cause: "slow_bitpro_probe",
            running: ["coro: arc_evolution_loop"]
          },
          components: {
            arc_evolution_loop: {
              status: "alive",
              stale: false,
              age_seconds: 4,
              in_flight: true,
              cycles: 14,
              consecutive_failures: 0,
              last_error: ""
            },
            ablation_sweep: {
              status: "degraded",
              stale: false,
              age_seconds: 95,
              in_flight: false,
              cycles: 3,
              consecutive_failures: 2,
              last_error: "Timeout while fetching klines"
            }
          }
        }
      ]
    }
  };
}

function makeRoutes(extra: Record<string, (url: string, init?: RequestInit) => Response | Promise<Response>> = {}) {
  const table: Record<string, (url: string, init?: RequestInit) => Response | Promise<Response>> = {
    "/api/harness/overview": () => jsonResponse(makeOverview()),
    "/api/healthz": () => jsonResponse(makeHealthz()),
    ...extra
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : String(input);
    if (table[url]) {
      return table[url](url, init);
    }
    const base = url.split("?")[0];
    if (table[base]) {
      return table[base](url, init);
    }
    return jsonResponse({ detail: `unmocked ${url}` }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, "", "/harness");
  document.documentElement.dataset.theme = "dark";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("mounts 4-tab HyperMonitor shell cleanly with strict on-demand fetching and theme persistence", async () => {
  const fetchMock = makeRoutes();

  render(<App />);

  expect(await screen.findByText("42ms")).toBeInTheDocument();
  expect(screen.getByText("HYPER")).toBeInTheDocument();
  expect(screen.getByText("TRADE")).toBeInTheDocument();
  expect(screen.getByText("AGENT CONTROL PLANE")).toBeInTheDocument();

  // Exact 4 nav tabs; legacy portfolio tab must not exist
  const nav = screen.getByRole("navigation", { name: "控制平面" });
  expect(within(nav).getByText("控制台与对话")).toBeInTheDocument();
  expect(within(nav).getByText("任务与进化")).toBeInTheDocument();
  expect(within(nav).getByText("记忆与治理")).toBeInTheDocument();
  expect(within(nav).getByText("告警与诊断")).toBeInTheDocument();
  expect(screen.queryByText("研究组合")).not.toBeInTheDocument();

  // Prompt starts empty without OKX legacy prefill
  const promptBox = screen.getByRole("textbox");
  expect(promptBox).toHaveValue("");
  expect(screen.queryByText(/OKX SWAP/)).not.toBeInTheDocument();

  // Only /api/harness/overview and /api/healthz were called on /harness mount
  const calledPaths = fetchMock.mock.calls.map(([u]) => String(u));
  expect(calledPaths.every((u) => u === "/api/harness/overview" || u === "/api/healthz")).toBe(true);
  expect(calledPaths).not.toContain("/api/auth/me");

  // Theme toggle persists light -> dark in localStorage
  const themeBtn = screen.getByRole("button", { name: "切换深浅外观" });
  fireEvent.click(themeBtn);
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(window.localStorage.getItem("hypertrade.theme.v1")).toBe("light");
});

test("tolerates degraded or 404 /api/healthz without breaking overview", async () => {
  makeRoutes({
    "/api/healthz": () => jsonResponse({ detail: "not found" }, 404)
  });

  render(<App />);

  expect(await screen.findByText("42ms")).toBeInTheDocument();
  expect(screen.queryByText("无法获取运行概览")).not.toBeInTheDocument();
});

test("redirects legacy routes to the consolidated 4 sections", async () => {
  makeRoutes({
    "/api/v1/arc/evolution": () =>
      jsonResponse({
        revision: 4,
        config: { exploration_provider: "deepseek", max_candidates: 3, max_research_per_day: 24 },
        budget: { period_used: 3, period_limit: 24, active_candidates: 1, sources: {} }
      }),
    "/api/portfolio/race-judge/status": () => jsonResponse([]),
    "/api/agent/missions": () => jsonResponse({ missions: [] }),
    "/api/memory": () => jsonResponse({ items: [], cognitive_items: [] }),
    "/api/memory/assertions": () => jsonResponse({ items: [] }),
    "/api/skills/proposals": () => jsonResponse({ items: [] }),
    "/api/skills/releases": () => jsonResponse({ items: [] }),
    "/api/strategy/library": () => jsonResponse({ source: "memory.strategy_knowledge", memory_count: 0, items: [] }),
    "/api/rag/search": () => jsonResponse({ hits: [] }),
    "/api/alerts": () => jsonResponse({ items: [] }),
    "/api/v1/arc/evolution/alerts": () => jsonResponse({ alerts: [] }),
    "/api/v1/arc/runtime-errors": () => jsonResponse({ items: [] })
  });

  window.history.replaceState({}, "", "/harness/portfolio");
  const first = render(<App />);
  expect(await screen.findByText("ARC 3-Slot 自主进化控制面")).toBeInTheDocument();
  first.unmount();

  window.history.replaceState({}, "", "/harness/rag");
  const second = render(<App />);
  expect(await screen.findByText("认知记忆层 (Semantic / Episodic / Hypothesis)")).toBeInTheDocument();
  second.unmount();

  window.history.replaceState({}, "", "/harness/quality");
  render(<App />);
  expect(await screen.findByText("Worker 循环心跳与 Stall 矩阵")).toBeInTheDocument();
});

test("Co-Pilot quick command, Cmd/Ctrl+Enter run clears prompt, auto-loads Flight Recorder, thread switcher & interrupt", async () => {
  const threadAfterTurn = {
    thread: {
      thread_id: "thr_alpha",
      title: "Alpha Session",
      status: "active",
      active_turn_id: "",
      event_cursor: 4
    },
    turns: [
      {
        turn_id: "trn_1",
        status: "completed",
        client_message_id: "web_turn_1",
        mission_id: "mis_flight_1",
        resolved_context: {}
      }
    ],
    items: [
      {
        item_id: "u1",
        turn_id: "trn_1",
        item_type: "user_message",
        status: "completed",
        sequence: 1,
        content: { text: "检查当前 ARC 3-Slot 变体占用、冷却状态、研究预算与最新扫描诊断" }
      },
      {
        item_id: "a1",
        turn_id: "trn_1",
        item_type: "agent_message",
        status: "completed",
        sequence: 4,
        content: { text: "3-Slot 当前占用 2/3，Slot 2 健康运行。" }
      }
    ]
  };

  let created = false;
  let completedTurn = false;
  const fetchMock = makeRoutes({
    "/api/agent/v1/threads": (_url, init) => {
      if (init?.method === "POST") {
        created = true;
        return jsonResponse({
          thread: { thread_id: "thr_alpha", title: "Web canonical workspace", status: "active", active_turn_id: "", event_cursor: 0 },
          turns: [],
          items: []
        });
      }
      return jsonResponse({
        items: [
          { thread_id: "thr_alpha", title: "Alpha Session", status: "active", active_turn_id: "", event_cursor: 4 },
          { thread_id: "thr_running", title: "Live Running Thread", status: "active", active_turn_id: "trn_live_9", event_cursor: 9 }
        ]
      });
    },
    "/api/agent/v1/threads/thr_alpha": () => jsonResponse(completedTurn ? threadAfterTurn : {
      thread: { thread_id: "thr_alpha", title: "Web canonical workspace", status: "active", active_turn_id: created ? "trn_1" : "", event_cursor: 1 },
      turns: [],
      items: []
    }),
    "/api/agent/v1/threads/thr_alpha/turns": () =>
      jsonResponse({ created: true, turn: { turn_id: "trn_1", status: "accepted" }, event_cursor: 1 }, 202),
    "/api/agent/v1/threads/thr_alpha/events/stream": () => {
      completedTurn = true;
      return sseResponse([
        { seq: 2, type: "tool_call.started", payload: { name: "bitpro_paper_dashboard" } },
        { seq: 3, type: "agent_message.delta", payload: { delta: "3-Slot 当前占用 2/3，Slot 2 健康运行。" } },
        { seq: 4, type: "turn.completed", payload: { mission_id: "mis_flight_1" } }
      ]);
    },
    "/api/agent/v1/threads/thr_alpha/turns/trn_1": () =>
      jsonResponse({ turn: { turn_id: "trn_1", status: "completed", mission_id: "mis_flight_1" }, items: [], event_cursor: 4 }),
    "/api/agent/runs/mis_flight_1/observability": () =>
      jsonResponse({
        schema_version: "1.0",
        run: {
          id: "mis_flight_1",
          status: "completed",
          provider: "deepseek",
          model: "deepseek-reasoner",
          duration_ms: 1450,
          started_at: "2026-11-18T10:30:00+08:00",
          completed_at: "2026-11-18T10:30:01+08:00"
        },
        usage: {
          reported: true,
          total_tokens: 1234,
          input_tokens: 800,
          output_tokens: 434
        },
        models: { request_count: 1, calls: [] },
        tools: { call_count: 1, total_execution_ms: 210 },
        memory: { read_count: 1, write_count: 0, items: [] },
        timeline: [],
        categories: { model: 1 },
        safety: {
          private_reasoning_stored: false,
          secrets_redacted: true,
          payload_mode: "summary"
        }
      }),
    "/api/agent/runs/mis_recent_1": () =>
      jsonResponse({
        id: "mis_recent_1",
        prompt: "诊断 3-Slot 进化预算与赛马表现",
        status: "completed",
        report_markdown: "历史报告正文：Slot 1 胜率 62%。",
        trace_events: [],
        run_state_json: { current_node: "completed" }
      }),
    "/api/agent/runs/mis_recent_1/observability": () =>
      jsonResponse({
        schema_version: "1.0",
        run: {
          id: "mis_recent_1",
          status: "completed",
          provider: "deepseek",
          model: "deepseek-reasoner",
          duration_ms: 980,
          started_at: "2026-11-18T09:00:00+08:00",
          completed_at: "2026-11-18T09:00:01+08:00"
        },
        usage: {
          reported: true,
          total_tokens: 2048,
          input_tokens: 1200,
          output_tokens: 848
        },
        models: { request_count: 1, calls: [] },
        tools: { call_count: 1, total_execution_ms: 120 },
        memory: { read_count: 0, write_count: 0, items: [] },
        timeline: [],
        categories: { model: 1 },
        safety: {
          private_reasoning_stored: false,
          secrets_redacted: true,
          payload_mode: "summary"
        }
      }),
    "/api/agent/v1/threads/thr_running": () =>
      jsonResponse({
        thread: {
          thread_id: "thr_running",
          title: "Live Running Thread",
          status: "active",
          active_turn_id: "trn_live_9",
          event_cursor: 9
        },
        turns: [{ turn_id: "trn_live_9", status: "running", client_message_id: "c9", resolved_context: {} }],
        items: []
      }),
    "/api/agent/v1/threads/thr_running/turns/trn_live_9/interrupt": () =>
      jsonResponse({ turn: { turn_id: "trn_live_9", status: "interrupted" }, items: [], event_cursor: 10 })
  });

  render(<App />);
  await screen.findByText("42ms");

  // Thread list is NOT fetched before clicking History Switcher
  expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/api/agent/v1/threads?"), expect.anything());

  // Click Quick-Command chip and submit via Ctrl+Enter
  fireEvent.click(screen.getByRole("button", { name: "3-Slot 进化状态" }));
  const textbox = screen.getByRole("textbox");
  expect((textbox as HTMLTextAreaElement).value).toContain("ARC 3-Slot");

  fireEvent.keyDown(textbox, { key: "Enter", ctrlKey: true });

  // Prompt cleared immediately once turn starts and answer/flight recorder appear
  await waitFor(() => expect(textbox).toHaveValue(""));
  expect(await screen.findByText(/1,234/)).toBeInTheDocument();
  expect(screen.getAllByText(/3-Slot 当前占用 2\/3/).length).toBeGreaterThanOrEqual(1);

  // Clicking a recent run loads its report & observability
  fireEvent.click(screen.getByRole("button", { name: /mis_recent_1/ }));
  expect(await screen.findByText(/历史报告正文：Slot 1 胜率 62%/)).toBeInTheDocument();
  expect(await screen.findByText(/2,048/)).toBeInTheDocument();

  // Thread Switcher loads threads ONLY on click, and selecting active-turn thread exposes Interrupt
  fireEvent.click(screen.getByRole("button", { name: "历史会话" }));
  const runningThreadBtn = await screen.findByRole("button", { name: /thr_running/ });
  fireEvent.click(runningThreadBtn);

  const interruptBtn = await screen.findByRole("button", { name: "中断" });
  fireEvent.click(interruptBtn);
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/agent/v1/threads/thr_running/turns/trn_live_9/interrupt",
      expect.objectContaining({ method: "POST" })
    )
  );
});

test("Missions & ARC Evolution tab renders 3-slot occupancy, triggers preset/scan/race-judge and Mission APIs", async () => {
  const fetchMock = makeRoutes({
    "/api/v1/arc/evolution": () =>
      jsonResponse({
        revision: 12,
        config: {
          enabled: true,
          exploration_provider: "deepseek",
          max_candidates: 3,
          max_research_per_day: 36
        },
        budget: {
          period_used: 8,
          period_limit: 36,
          active_candidates: 2,
          sources: {
            slot_1_momentum: {
              source_strategy_id: 1,
              target_id: "slot_1_momentum",
              observing_slots: 2,
              slot_limit: 3,
              slots_open: 1,
              cooldown_hours: 0,
              in_research: true,
              busy: true,
              active_slot_variants: [{ variant_id: 12 }],
              failure_streak: 0,
              failure_reason: ""
            },
            slot_2_reversion: {
              source_strategy_id: 2,
              target_id: "slot_2_reversion",
              observing_slots: 1,
              slot_limit: 3,
              slots_open: 2,
              cooldown_hours: 12,
              in_research: false,
              busy: false,
              active_slot_variants: [],
              failure_streak: 2,
              failure_reason: "recent ablation timeout"
            }
          }
        }
      }),
    "/api/v1/arc/evolution/preset": () => jsonResponse({ ok: true }),
    "/api/v1/arc/evolution/scan": () => jsonResponse({ queued: 1 }),
    "/api/portfolio/race-judge/status": () =>
      jsonResponse([
        {
          parent_strategy_id: 1,
          challenger_strategy_id: 12,
          parent_name: "Momentum Core",
          challenger_name: "Momentum V2",
          slot_no: 1,
          state: "observing",
          observed_hours: 140,
          target_hours: 337,
          excess_return_pct: 4.85,
          sign_test_p: 0.0321,
          eligible: false,
          reason: "Awaiting 337h full window"
        }
      ]),
    "/api/portfolio/race-judge/run-now": () =>
      jsonResponse([
        {
          parent_strategy_id: 1,
          challenger_strategy_id: 12,
          parent_name: "Momentum Core",
          challenger_name: "Momentum V2",
          slot_no: 1,
          state: "eligible",
          observed_hours: 337,
          target_hours: 337,
          excess_return_pct: 6.12,
          sign_test_p: 0.008,
          eligible: true,
          reason: "Statistically validated"
        }
      ]),
    "/api/agent/missions": (_url, init) => {
      if (init?.method === "POST") {
        return jsonResponse({
          mission_id: "mis_new_1",
          objective: "验证 Slot 1 因子稳健性",
          status: "queued",
          current_step_index: 0,
          plan: [],
          unknowns: []
        });
      }
      return jsonResponse({
        missions: [
          {
            mission_id: "mis_evo_1",
            objective: "审查 Slot 1 候选替换资格",
            status: "running",
            current_step_index: 0,
            plan: [],
            unknowns: []
          }
        ]
      });
    },
    "/api/agent/missions/mis_evo_1": () =>
      jsonResponse({
        mission_id: "mis_evo_1",
        objective: "审查 Slot 1 候选替换资格",
        status: "running",
        current_step_index: 0,
        plan: [],
        unknowns: []
      }),
    "/api/agent/missions/mis_evo_1/events": () => jsonResponse({ events: [] }),
    "/api/agent/missions/mis_new_1": () =>
      jsonResponse({
        mission_id: "mis_new_1",
        objective: "验证 Slot 1 因子稳健性",
        status: "queued",
        current_step_index: 0,
        plan: [],
        unknowns: []
      }),
    "/api/agent/missions/mis_new_1/events": () => jsonResponse({ events: [] })
  });

  render(<App />);
  fireEvent.click(screen.getByRole("link", { name: "任务与进化" }));

  expect(await screen.findByText("ARC 3-Slot 自主进化控制面")).toBeInTheDocument();
  expect(await screen.findByText("#1 · slot_1_momentum")).toBeInTheDocument();
  expect(await screen.findByText("#1 → #12 (Slot 1)")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "应用 production_3slot 预设" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/arc/evolution/preset",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ preset: "production_3slot" })
      })
    )
  );

  fireEvent.click(screen.getByRole("button", { name: "触发预扫描" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/arc/evolution/scan",
      expect.objectContaining({ method: "POST" })
    )
  );

  fireEvent.click(screen.getByRole("button", { name: "立即评判" }));
  expect(await screen.findByText(/Statistically validated/)).toBeInTheDocument();
});

test("Knowledge & Memory tab loads cognitive tiers, kind/tag filters, last_used_at, and auto-searches RAG", async () => {
  const fetchMock = makeRoutes({
    "/api/memory": (url) =>
      jsonResponse({
        items: [
          {
            id: "mem_1",
            kind: "lesson",
            content: url.includes("tag=btc") ? "BTC 筛选后因果规则" : "高波动窗口减仓 30%",
            importance: 0.9,
            confidence: 0.88,
            usage_count: 5,
            source_tool: "bitpro_paper_dashboard",
            source_run_id: "run_mem_1",
            last_used_at: "2026-11-18T08:15:00+08:00",
            tags: ["risk", "volatility"],
            status: "active"
          }
        ],
        cognitive: {
          active_semantic_count: 4,
          superseded_semantic_count: 1,
          episodic_count: 7,
          hypothesis_count: 3
        },
        cognitive_items: [
          {
            tier: "semantic",
            id: "sem_1",
            kind: "causal_rule",
            claim: "Funding 极端正值时趋势突破胜率下降",
            regimes: ["high_vol"],
            symbols: ["BTCUSDT"],
            timeframe: "4h",
            confidence: 0.91,
            distillation_version: 2,
            derived_episode_count: 6,
            status: "active"
          },
          {
            tier: "episodic",
            id: "ep_1",
            kind: "race_outcome",
            summary: "Slot 1 challenger #12 超越 parent #1 (+6.1%)",
            market_regime: "trend_up",
            timeframe: "1h",
            mission_id: "mis_ep_1",
            raw_evidence_ref: "race:1:12"
          }
        ]
      }),
    "/api/memory/assertions": () =>
      jsonResponse({
        items: [
          {
            assertion_id: "asrt_1",
            claim: "Paper 滑点估计偏低",
            status: "pending",
            source_ids: ["ev_1"],
            confidence: 0.85
          }
        ]
      }),
    "/api/skills/proposals": () => jsonResponse({ items: [] }),
    "/api/skills/releases": () => jsonResponse({ items: [] }),
    "/api/strategy/library": () => jsonResponse({ source: "memory.strategy_knowledge", memory_count: 1, items: [] }),
    "/api/rag/search": () =>
      jsonResponse({
        hits: [
          {
            document_id: "doc_1",
            title: "Risk Gate Spec",
            excerpt: "All mainnet mutations require operator confirmation.",
            score: 0.92
          }
        ]
      })
  });

  render(<App />);
  fireEvent.click(screen.getByRole("link", { name: "记忆与治理" }));

  // Auto-searched RAG with query=risk & cognitive items loaded
  expect(await screen.findByText("Funding 极端正值时趋势突破胜率下降")).toBeInTheDocument();
  expect(await screen.findByText("Slot 1 challenger #12 超越 parent #1 (+6.1%)")).toBeInTheDocument();
  expect(await screen.findByText("Risk Gate Spec")).toBeInTheDocument();
  expect(await screen.findByText("最近复用")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/rag/search?query=risk",
    expect.objectContaining({ method: "GET" })
  );

  // Kind & tag filter triggers parameterized /api/memory fetch
  fireEvent.change(screen.getByLabelText("类型过滤"), { target: { value: "lesson" } });
  fireEvent.change(screen.getByLabelText("标签过滤"), { target: { value: "btc" } });
  const queryButtons = screen.getAllByRole("button", { name: "查询" });
  fireEvent.click(queryButtons[0]);

  expect((await screen.findAllByText("BTC 筛选后因果规则")).length).toBeGreaterThanOrEqual(1);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/memory?kind=lesson&tag=btc",
    expect.objectContaining({ method: "GET" })
  );
});

test("System & Diagnostics tab renders /api/healthz worker loops & stalls, acks ARC alerts, omits fake trigger text", async () => {
  const fetchMock = makeRoutes({
    "/api/alerts": () =>
      jsonResponse({
        items: [
          { id: "alt_1", code: "probe_warn", title: "Probe Slow", severity: "warn", message: "Latency elevated" }
        ]
      }),
    "/api/v1/arc/evolution/alerts": () =>
      jsonResponse({
        alerts: [
          {
            id: "arc_alt_1",
            code: "slot_cooldown_stuck",
            strategy_id: 12,
            status: "open",
            message: "Slot 2 exceeded failure threshold"
          }
        ]
      }),
    "/api/v1/arc/evolution/alerts/arc_alt_1/ack": () => jsonResponse({ ok: true }),
    "/api/v1/arc/runtime-errors": () =>
      jsonResponse({
        items: [
          {
            error_id: "err_1",
            component: "avo_runner",
            exception_type: "TimeoutError",
            message: "Upstream BitPro timeout",
            occurrences: 3,
            mission_id: "mis_err_1"
          }
        ]
      })
  });

  render(<App />);
  fireEvent.click(screen.getByRole("link", { name: "告警与诊断" }));

  expect(await screen.findByText("Worker 循环心跳与 Stall 矩阵")).toBeInTheDocument();
  expect(await screen.findByText("worker-alpha")).toBeInTheDocument();
  expect(await screen.findByText(/Last Stall: 18\.4s/)).toBeInTheDocument();
  expect(screen.getAllByText(/ablation_sweep/).length).toBeGreaterThanOrEqual(2);
  expect(await screen.findByText(/Slot 2 exceeded failure threshold/)).toBeInTheDocument();
  expect(await screen.findByText(/Upstream BitPro timeout/)).toBeInTheDocument();

  // Never render hardcoded misleading background-trigger claim
  expect(screen.queryByText(/后台触发保持禁用/)).not.toBeInTheDocument();

  // Ack open ARC alert
  fireEvent.click(screen.getByRole("button", { name: "确认" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/arc/evolution/alerts/arc_alt_1/ack",
      expect.objectContaining({ method: "POST" })
    )
  );
});

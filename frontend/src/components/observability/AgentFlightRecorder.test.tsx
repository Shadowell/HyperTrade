import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { AgentFlightRecorder, RunObservability } from "./AgentFlightRecorder";

const fixture: RunObservability = {
  schema_version: "agent-observability-v1",
  run: {
    id: "run_flight_001",
    status: "completed",
    provider: "codex",
    model: "gpt-5.5",
    duration_ms: 1480,
    started_at: "2026-07-10T00:00:00Z",
    completed_at: "2026-07-10T00:00:01Z"
  },
  usage: {
    input_tokens: 1200,
    output_tokens: 300,
    cached_input_tokens: 700,
    reasoning_tokens: 120,
    total_tokens: 1500,
    request_count: 2,
    reported: true
  },
  models: { request_count: 2, calls: [] },
  tools: { call_count: 1, error_count: 0, total_execution_ms: 42 },
  memory: {
    read_count: 1,
    write_count: 0,
    read_ids: ["mem_risk_001"],
    write_ids: [],
    items: [
      {
        id: "mem_risk_001",
        kind: "risk_note",
        content_preview: "Keep the risk budget conservative.",
        source_run_id: "run_prior",
        source_tool: "memory.write",
        importance: "0.8000",
        confidence: "0.9000",
        usage_count: 3,
        created_at: "2026-07-09T00:00:00Z"
      }
    ]
  },
  timeline: [
    {
      id: "evt_model",
      sequence: 1,
      category: "model",
      name: "model_call",
      status: "completed",
      created_at: "2026-07-10T00:00:00Z",
      offset_ms: 5,
      duration_ms: 320,
      summary: "iteration 1 · 1 tool calls · 900 tokens",
      usage: { input_tokens: 750, output_tokens: 150, total_tokens: 900, reported: true },
      memory_ids: []
    },
    {
      id: "evt_memory",
      sequence: 2,
      category: "memory",
      name: "memory.search",
      status: "completed",
      created_at: "2026-07-10T00:00:00Z",
      offset_ms: 330,
      duration_ms: 18,
      summary: "read 1 audited item",
      memory_ids: ["mem_risk_001"]
    }
  ],
  categories: { graph: 0, model: 1, tool: 0, memory: 1, policy: 0 },
  safety: {
    private_reasoning_stored: false,
    secrets_redacted: true,
    payload_mode: "summary"
  }
};

afterEach(cleanup);

test("renders token ledger and drills into memory trace without reasoning text", () => {
  render(<AgentFlightRecorder data={fixture} language="zh" />);

  expect(screen.getByText("运行黑匣子")).toBeInTheDocument();
  expect(screen.getByText("codex / gpt-5.5")).toBeInTheDocument();
  expect(screen.getAllByText("1,500").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("未存储私有思维链")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /MEMmemory\.search/ }));

  expect(screen.getByText("mem_risk_001")).toBeInTheDocument();
  expect(screen.getByText(/Keep the risk budget conservative/)).toBeInTheDocument();
  expect(screen.queryByText(/chain-of-thought/i)).not.toBeInTheDocument();
});

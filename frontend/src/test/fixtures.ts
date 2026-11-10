import { EMPTY_OVERVIEW } from "../lib/emptyOverview";
import type { HarnessOverview } from "../types";

export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body
  } as Response;
}

/** A small but realistic overview, as the API would return it for a configured deployment. */
export function liveOverview(overrides: Partial<HarnessOverview> = {}): HarnessOverview {
  return {
    ...EMPTY_OVERVIEW,
    generated_at: "2026-11-10T12:52:38+00:00",
    providers: [
      {
        name: "codex",
        display_name: "Codex",
        model: "gpt-6-astra",
        enabled: true,
        default: true,
        key_status: "configured"
      }
    ],
    trace: {
      total_count: 2,
      recent_events: [
        { id: "t1", tool_name: "market.summary", status: "ready" },
        { id: "t2", tool_name: "rag.search", status: "ready" }
      ]
    },
    rag: { document_count: 12, chunk_count: 340 },
    memory: { active_count: 7, total_count: 9, latest_created_at: null },
    market: { ticker_count: 344, latest_ticker_at: null, latest_update_age_seconds: 5, top_movers: [] },
    bitpro: {
      adapter: "mcp_non_live_lifecycle",
      configured: true,
      api_base: "https://bitpro.example/api/v2",
      auth_header: "X-BitPro-MCP-Token",
      token_configured: true,
      live_write_enabled: false,
      tools: ["bitpro_capabilities", "bitpro_health"]
    },
    ...overrides
  };
}

import { Channel, invoke } from "@tauri-apps/api/core";

export type ConnectionResult = {
  status: string;
  service: string;
};

export type AgentStreamEvent = {
  event?: string;
  text?: string;
  count?: number;
  code?: string;
  status?: string;
  tool_name?: string;
  run?: Record<string, unknown>;
  error?: Record<string, unknown> | string;
  [key: string]: unknown;
};

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export const DEFAULT_API_BASE =
  import.meta.env.VITE_HT_API_BASE?.trim() || "http://47.79.36.92:3333";

function isTauriRuntime() {
  return typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);
}

export async function checkConnection(apiBase: string): Promise<ConnectionResult> {
  if (!isTauriRuntime()) {
    return { status: "ok", service: "hypertrade-preview" };
  }
  return invoke<ConnectionResult>("check_connection", { apiBase });
}

export async function runAgent(
  apiBase: string,
  prompt: string,
  idempotencyKey: string,
  onEvent: (event: AgentStreamEvent) => void
): Promise<void> {
  if (!isTauriRuntime()) {
    await previewRun(onEvent);
    return;
  }

  const onEventChannel = new Channel<AgentStreamEvent>();
  onEventChannel.onmessage = onEvent;
  await invoke("stream_agent", {
    apiBase,
    prompt,
    idempotencyKey,
    onEvent: onEventChannel
  });
}

export async function setPanelOpen(open: boolean): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("set_panel_open", { open });
  }
}

export async function startDragging(): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("start_dragging");
  }
}

export async function hideWindow(): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("hide_window");
  }
}

async function previewRun(onEvent: (event: AgentStreamEvent) => void) {
  onEvent({ event: "answer_delta", text: "已受理只读研究请求，正在验证证据。" });
  await delay(240);
  onEvent({ event: "evidence_ready", count: 3 });
  await delay(360);
  onEvent({
    event: "answer_delta",
    text: "当前市场方向仍需结合最新行情确认。已识别波动扩张信号，但证据不足以支持交易执行。"
  });
  onEvent({
    event: "final",
    run: {
      id: "preview_mission",
      status: "completed",
      report_json: {
        operator_response: {
          decision: "当前市场方向仍需结合最新行情确认。已识别波动扩张信号，但证据不足以支持交易执行。",
          unknowns: ["部分合约的资金费率快照尚未完成同步"]
        }
      }
    }
  });
}

function delay(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

import type { AgentStreamEvent } from "./bridge";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  state: "complete" | "streaming" | "error";
  evidenceCount?: number;
  unknowns?: string[];
};

export function applyAgentEvent(
  message: ChatMessage,
  payload: AgentStreamEvent
): ChatMessage {
  const eventName = String(payload.event ?? "message");

  if (eventName === "answer_delta" && typeof payload.text === "string") {
    return {
      ...message,
      text: appendDistinct(message.text, payload.text.trim()),
      state: "streaming"
    };
  }

  if (eventName === "evidence_ready") {
    return {
      ...message,
      evidenceCount: Number.isFinite(Number(payload.count)) ? Number(payload.count) : 0
    };
  }

  if (eventName === "final" || eventName === "run_completed") {
    const finalProjection = readFinalProjection(payload.run);
    return {
      ...message,
      // The final server projection is the auditable answer. Replace transient
      // progress text so an operator sees the actual strategy facts, not a status line.
      text: finalProjection.text || message.text,
      unknowns: finalProjection.unknowns,
      state: "complete"
    };
  }

  if (eventName === "warning") {
    const warning = typeof payload.text === "string" ? payload.text.trim() : "研究结果存在未确认项。";
    return {
      ...message,
      text: appendDistinct(message.text, warning),
      state: payload.code === "mission_runtime_error" ? "error" : "streaming"
    };
  }

  if (eventName === "error") {
    return {
      ...message,
      text: appendDistinct(message.text, formatError(payload.error)),
      state: "error"
    };
  }

  return message;
}

export function eventActivity(payload: AgentStreamEvent): string {
  const eventName = String(payload.event ?? "message");
  if (eventName === "evidence_ready") {
    return `已验证 ${Number(payload.count ?? 0)} 条证据`;
  }
  if (eventName === "answer_delta") {
    return "正在组织结论";
  }
  if (eventName === "final" || eventName === "run_completed") {
    return "研究完成";
  }
  if (eventName === "error") {
    return "运行失败";
  }
  if (typeof payload.tool_name === "string") {
    return `正在调用 ${payload.tool_name}`;
  }
  return eventName.replaceAll("_", " ");
}

function readFinalProjection(run: unknown): { text: string; unknowns: string[] } {
  if (!isRecord(run)) {
    return { text: "", unknowns: [] };
  }
  const reportJson = isRecord(run.report_json) ? run.report_json : {};
  const operatorResponse = isRecord(reportJson.operator_response)
    ? reportJson.operator_response
    : {};
  const decision = typeof operatorResponse.decision === "string"
    ? operatorResponse.decision.trim()
    : "";
  const report = typeof run.report_markdown === "string" ? run.report_markdown.trim() : "";
  const unknowns = Array.isArray(operatorResponse.unknowns)
    ? operatorResponse.unknowns.filter((item): item is string => typeof item === "string")
    : [];
  return { text: report || decision, unknowns };
}

function appendDistinct(current: string, next: string) {
  const cleanCurrent = current.trim();
  const cleanNext = next.trim();
  if (!cleanNext || cleanCurrent.includes(cleanNext)) {
    return cleanCurrent;
  }
  return cleanCurrent ? `${cleanCurrent}\n\n${cleanNext}` : cleanNext;
}

function formatError(error: unknown) {
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }
  if (isRecord(error)) {
    if (typeof error.code === "string") {
      return `运行失败：${error.code}`;
    }
    if (typeof error.category === "string") {
      return `运行失败：${error.category}`;
    }
  }
  return "研究运行失败，请检查服务连接后重试。";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

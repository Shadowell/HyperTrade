export const THREAD_SESSION_STORAGE_KEY = "hypertrade.agent.thread.v1";

export const TERMINAL_TURN_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "expired"
]);
const WAITING_TURN_STATUSES = new Set(["waiting_input", "waiting_approval"]);

export type ThreadProjection = {
  thread_id: string;
  title: string;
  status: "active" | "archived" | "quarantined";
  active_turn_id: string;
  event_cursor: number;
};

export type TurnProjection = {
  turn_id: string;
  status: string;
  client_message_id: string;
  mission_id: string;
  resolved_context: Record<string, unknown>;
};

export type ThreadItem = {
  item_id: string;
  turn_id: string;
  item_type:
    | "user_message"
    | "agent_message"
    | "tool_call"
    | "evidence_ready"
    | "input_request"
    | "approval_request";
  status: string;
  sequence: number;
  content: Record<string, unknown>;
};

export type ThreadSnapshot = {
  thread: ThreadProjection;
  turns: TurnProjection[];
  items: ThreadItem[];
};

export type ThreadEvent = {
  event_id: string;
  event_type: string;
  thread_sequence: number;
  payload: Record<string, unknown>;
};

export type ThreadSessionPointer = {
  threadId: string;
  cursor: number;
};

export type ThreadMessage = {
  id: string;
  role: "user" | "agent" | "system";
  kind: ThreadItem["item_type"];
  status: string;
  text: string;
};

export type ThreadPresentation = {
  answer: string;
  messages: ThreadMessage[];
  tools: Array<{ id: string; name: string; status: string }>;
  evidence: string[];
  warnings: string[];
  resolvedRefs: string[];
  status: string;
};

export class ThreadProtocolRequestError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
  }
}

type FetchLike = typeof fetch;

export function readThreadSession(storage: Storage | undefined): ThreadSessionPointer | null {
  if (!storage) return null;
  const raw = storage.getItem(THREAD_SESSION_STORAGE_KEY);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Record<string, unknown>;
    if (typeof value.threadId !== "string" || !value.threadId.startsWith("thr_")) return null;
    const cursor = typeof value.cursor === "number" && value.cursor >= 0 ? value.cursor : 0;
    return { threadId: value.threadId, cursor };
  } catch {
    return null;
  }
}

export function writeThreadSession(
  storage: Storage | undefined,
  pointer: ThreadSessionPointer
): void {
  if (!storage) return;
  storage.setItem(THREAD_SESSION_STORAGE_KEY, JSON.stringify(pointer));
}

export function clearThreadSession(storage: Storage | undefined): void {
  if (!storage) return;
  storage.removeItem(THREAD_SESSION_STORAGE_KEY);
}

export async function createAgentThread(
  fetchImpl: FetchLike = fetch
): Promise<ThreadSnapshot> {
  return requestJson<ThreadSnapshot>(fetchImpl, "/api/agent/v1/threads", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Web canonical workspace", retention: "durable" })
  });
}

export async function getAgentThread(
  threadId: string,
  fetchImpl: FetchLike = fetch
): Promise<ThreadSnapshot> {
  return requestJson<ThreadSnapshot>(
    fetchImpl,
    `/api/agent/v1/threads/${encodeURIComponent(threadId)}`,
    { credentials: "include" }
  );
}

export async function startAgentTurn(
  threadId: string,
  input: string,
  clientMessageId: string,
  fetchImpl: FetchLike = fetch
): Promise<{ created: boolean; turn: TurnProjection; event_cursor: number }> {
  return requestJson(fetchImpl, `/api/agent/v1/threads/${encodeURIComponent(threadId)}/turns`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input, client_message_id: clientMessageId })
  });
}

export async function getAgentTurn(
  threadId: string,
  turnId: string,
  fetchImpl: FetchLike = fetch
): Promise<{ turn: TurnProjection; items: ThreadItem[]; event_cursor: number }> {
  return requestJson(
    fetchImpl,
    `/api/agent/v1/threads/${encodeURIComponent(threadId)}/turns/${encodeURIComponent(turnId)}`,
    { credentials: "include" }
  );
}

export async function archiveAgentThread(
  threadId: string,
  fetchImpl: FetchLike = fetch
): Promise<ThreadSnapshot> {
  return requestJson(
    fetchImpl,
    `/api/agent/v1/threads/${encodeURIComponent(threadId)}/archive`,
    { method: "POST", credentials: "include" }
  );
}

export async function followAgentTurn({
  threadId,
  turnId,
  after,
  onEvent,
  onReconnecting,
  onCursor,
  fetchImpl = fetch,
  maxReconnects = 5
}: {
  threadId: string;
  turnId: string;
  after: number;
  onEvent: (event: ThreadEvent) => void;
  onReconnecting: (attempt: number) => void;
  onCursor: (cursor: number) => void;
  fetchImpl?: FetchLike;
  maxReconnects?: number;
}): Promise<{ snapshot: ThreadSnapshot; cursor: number }> {
  let cursor = after;
  let reconnects = 0;
  while (reconnects <= maxReconnects) {
    try {
      const response = await fetchImpl(
        `/api/agent/v1/threads/${encodeURIComponent(threadId)}/events/stream?after=${cursor}`,
        {
          credentials: "include",
          headers: { "Last-Event-ID": String(cursor) }
        }
      );
      if (!response.ok || !response.body) {
        throw await responseError(response);
      }
      cursor = await consumeThreadEventStream(
        response.body,
        cursor,
        (event) => {
          cursor = event.thread_sequence;
          onCursor(cursor);
          onEvent(event);
        },
        (event) =>
          event.event_type === "turn.input_requested" ||
          event.event_type === "turn.approval_requested"
      );
      const terminal = await getAgentTurn(threadId, turnId, fetchImpl);
      if (
        TERMINAL_TURN_STATUSES.has(terminal.turn.status) ||
        WAITING_TURN_STATUSES.has(terminal.turn.status)
      ) {
        return { snapshot: await getAgentThread(threadId, fetchImpl), cursor };
      }
      throw new ThreadProtocolRequestError("event stream ended without a terminal Turn", 502);
    } catch (error) {
      if (error instanceof ThreadProtocolRequestError && error.status < 500) throw error;
      reconnects += 1;
      if (reconnects > maxReconnects) {
        throw error instanceof Error ? error : new Error("canonical Thread stream failed");
      }
      onReconnecting(reconnects);
    }
  }
  throw new Error("canonical Thread stream failed");
}

export async function consumeThreadEventStream(
  body: ReadableStream<Uint8Array>,
  initialCursor: number,
  onEvent: (event: ThreadEvent) => void,
  shouldStop: (event: ThreadEvent) => boolean = () => false
): Promise<number> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let cursor = initialCursor;
  let stop = false;
  while (true) {
    const { value, done } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const event = parseThreadEventFrame(frame);
      if (!event || event.thread_sequence <= cursor) continue;
      cursor = event.thread_sequence;
      onEvent(event);
      stop = shouldStop(event);
      if (stop) break;
    }
    if (stop) {
      await reader.cancel();
      return cursor;
    }
    if (done) break;
  }
  if (buffer.trim()) {
    const event = parseThreadEventFrame(buffer);
    if (event && event.thread_sequence > cursor) {
      cursor = event.thread_sequence;
      onEvent(event);
    }
  }
  return cursor;
}

export function presentThread(snapshot: ThreadSnapshot | null): ThreadPresentation {
  if (!snapshot) {
    return { answer: "", messages: [], tools: [], evidence: [], warnings: [], resolvedRefs: [], status: "ready" };
  }
  const messages: ThreadMessage[] = [];
  const tools: ThreadPresentation["tools"] = [];
  const evidence: string[] = [];
  const warnings: string[] = [];
  let answer = "";
  for (const item of snapshot.items) {
    if (item.item_type === "tool_call") {
      tools.push({
        id: item.item_id,
        name: stringValue(item.content.capability_id) || "governed_read",
        status: item.status
      });
      continue;
    }
    if (item.item_type === "evidence_ready") {
      evidence.push(...stringList(item.content.evidence));
      continue;
    }
    const text = itemText(item);
    if (item.item_type === "agent_message") {
      answer = text || answer;
      warnings.push(...stringList(item.content.unknowns));
    }
    if (item.item_type === "input_request" || item.item_type === "approval_request") {
      warnings.push(text);
    }
    if (text) {
      messages.push({
        id: item.item_id,
        role: item.item_type === "user_message" ? "user" : item.item_type === "agent_message" ? "agent" : "system",
        kind: item.item_type,
        status: item.status,
        text
      });
    }
  }
  const latestTurn = snapshot.turns.at(-1);
  const refs = resolvedReferenceValues(latestTurn?.resolved_context);
  return {
    answer,
    messages,
    tools,
    evidence,
    warnings: warnings.filter(Boolean),
    resolvedRefs: refs,
    status: latestTurn?.status ?? snapshot.thread.status
  };
}

export function formatThreadEvent(event: ThreadEvent): string {
  const capability = isRecord(event.payload.content)
    ? stringValue(event.payload.content.capability_id)
    : "";
  return `${event.event_type}${capability ? ` · ${capability}` : ""} · #${event.thread_sequence}`;
}

async function requestJson<T>(fetchImpl: FetchLike, input: string, init?: RequestInit): Promise<T> {
  const response = await fetchImpl(input, init);
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as T;
}

async function responseError(response: Response): Promise<ThreadProtocolRequestError> {
  let detail = `Thread protocol request failed (${response.status})`;
  try {
    const payload = (await response.json()) as Record<string, unknown>;
    if (typeof payload.detail === "string") detail = payload.detail;
  } catch {
    // Preserve the bounded status fallback when the server did not return JSON.
  }
  return new ThreadProtocolRequestError(detail, response.status);
}

function parseThreadEventFrame(frame: string): ThreadEvent | null {
  const data = frame
    .split("\n")
    .find((line) => line.startsWith("data: "))
    ?.slice(6);
  if (!data) return null;
  const payload = JSON.parse(data) as ThreadEvent;
  return typeof payload.thread_sequence === "number" ? payload : null;
}

function itemText(item: ThreadItem): string {
  return stringValue(item.content.text) || stringValue(item.content.message);
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return typeof value === "string" && value ? [value] : [];
  return value.map((item) => (typeof item === "string" ? item : JSON.stringify(item)));
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function resolvedReferenceValues(context: Record<string, unknown> | undefined): string[] {
  if (!context) return [];
  const resolvedSubject = stringValue(context.resolved_subject);
  if (resolvedSubject) return [resolvedSubject];
  const values = [
    ...stringList(context.subject_refs),
    stringValue(context.symbol),
    stringValue(context.instrument),
    stringValue(context.account),
    stringValue(context.environment)
  ].filter(Boolean);
  return [...new Set(values)];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

import { expect, test, vi } from "vitest";

import {
  consumeThreadEventStream,
  followAgentTurn,
  presentThread,
  startAgentTurn,
  ThreadSnapshot,
  ThreadProtocolRequestError,
  writeThreadSession,
  readThreadSession
} from "./agentThread";

test("starts a canonical Turn without browser supplied history", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    expect(JSON.parse(String(init?.body))).toEqual({
      input: "后者最大回撤多少？",
      client_message_id: "web-message-1"
    });
    expect(String(init?.body)).not.toContain("prior_turns");
    return new Response(
      JSON.stringify({
        created: true,
        turn: { turn_id: "trn_1", status: "accepted" },
        event_cursor: 2
      }),
      { status: 202, headers: { "Content-Type": "application/json" } }
    );
  });

  await startAgentTurn("thr_1", "后者最大回撤多少？", "web-message-1", fetchMock);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agent/v1/threads/thr_1/turns",
    expect.objectContaining({ method: "POST", credentials: "include" })
  );
});

test("preserves explicit 409 idempotency conflict semantics", async () => {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ detail: "client_message_id is bound to different request content" }), {
      status: 409,
      headers: { "Content-Type": "application/json" }
    })
  );

  await expect(startAgentTurn("thr_1", "changed", "web-message-1", fetchMock)).rejects.toEqual(
    expect.objectContaining<Partial<ThreadProtocolRequestError>>({
      status: 409,
      message: "client_message_id is bound to different request content"
    })
  );
});

test("parses split SSE frames and ignores replayed cursor events", async () => {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode('id: 2\nevent: tool_call.started\ndata: {"event_id":"e2","event_type":"tool_call.started","thread_sequence":2,"payload":{}}\n'));
      controller.enqueue(encoder.encode('\nid: 3\nevent: turn.completed\ndata: {"event_id":"e3","event_type":"turn.completed","thread_sequence":3,"payload":{}}\n\n'));
      controller.close();
    }
  });
  const seen: number[] = [];

  const cursor = await consumeThreadEventStream(body, 2, (event) => seen.push(event.thread_sequence));

  expect(cursor).toBe(3);
  expect(seen).toEqual([3]);
});

test("reconnects by cursor across tool, evidence, and answer stream boundaries", async () => {
  const frames = [
    [2, "tool_call.started"],
    [3, "evidence_ready.completed"],
    [4, "agent_message.delta"],
    [5, "turn.completed"]
  ] as const;
  let streamIndex = 0;
  const streamUrls: string[] = [];
  const snapshot = {
    thread: { thread_id: "thr_reconnect", title: "Web", status: "active", active_turn_id: "", event_cursor: 5 },
    turns: [{ turn_id: "trn_reconnect", status: "completed", client_message_id: "web-1", mission_id: "mis_1", resolved_context: {} }],
    items: []
  } satisfies ThreadSnapshot;
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/events/stream")) {
      streamUrls.push(url);
      const [sequence, eventType] = frames[streamIndex++];
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(
              `id: ${sequence}\nevent: ${eventType}\ndata: ${JSON.stringify({ event_id: `e${sequence}`, event_type: eventType, thread_sequence: sequence, payload: {} })}\n\n`
            )
          );
          controller.close();
        }
      });
      return new Response(body, { status: 200 });
    }
    if (url.endsWith("/turns/trn_reconnect")) {
      return new Response(
        JSON.stringify({
          turn: { ...snapshot.turns[0], status: streamIndex >= frames.length ? "completed" : "running" },
          items: [],
          event_cursor: streamIndex + 1
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.endsWith("/api/agent/v1/threads/thr_reconnect")) {
      return new Response(JSON.stringify(snapshot), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
    return new Response("not found", { status: 404 });
  });
  const seen: string[] = [];
  const reconnects: number[] = [];

  const result = await followAgentTurn({
    threadId: "thr_reconnect",
    turnId: "trn_reconnect",
    after: 0,
    fetchImpl: fetchMock,
    onEvent: (event) => seen.push(event.event_type),
    onCursor: () => undefined,
    onReconnecting: (attempt) => reconnects.push(attempt)
  });

  expect(result.cursor).toBe(5);
  expect(seen).toEqual(frames.map(([, eventType]) => eventType));
  expect(seen.filter((eventType) => eventType === "turn.completed")).toHaveLength(1);
  expect(streamUrls).toEqual([
    expect.stringContaining("after=0"),
    expect.stringContaining("after=2"),
    expect.stringContaining("after=3"),
    expect.stringContaining("after=4")
  ]);
  expect(reconnects).toEqual([1, 2, 3]);
});

test("stores only the Thread pointer and presents server Items", () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    clear: () => values.clear(),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() { return values.size; }
  } satisfies Storage;
  writeThreadSession(storage, { threadId: "thr_web", cursor: 8 });
  expect(readThreadSession(storage)).toEqual({ threadId: "thr_web", cursor: 8 });
  expect(storage.getItem("hypertrade.agent.thread.v1")).not.toContain("message");

  const snapshot = {
    thread: { thread_id: "thr_web", title: "Web", status: "active", active_turn_id: "", event_cursor: 8 },
    turns: [
      {
        turn_id: "trn_1",
        status: "completed",
        client_message_id: "web-1",
        mission_id: "mis_1",
        resolved_context: { subject_refs: ["mean_reversion_v1"], resolved_subject: "mean_reversion_v1" }
      }
    ],
    items: [
      { item_id: "u1", turn_id: "trn_1", item_type: "user_message", status: "completed", sequence: 2, content: { text: "后者最大回撤多少？" } },
      { item_id: "t1", turn_id: "trn_1", item_type: "tool_call", status: "completed", sequence: 5, content: { capability_id: "strategy.performance" } },
      { item_id: "a1", turn_id: "trn_1", item_type: "agent_message", status: "completed", sequence: 7, content: { text: "缺少可比回撤数据。", unknowns: ["max_drawdown unavailable"] } }
    ]
  } satisfies ThreadSnapshot;

  expect(presentThread(snapshot)).toMatchObject({
    answer: "缺少可比回撤数据。",
    status: "completed",
    resolvedRefs: ["mean_reversion_v1"],
    warnings: ["max_drawdown unavailable"]
  });
});

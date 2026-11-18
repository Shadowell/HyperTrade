import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  archiveAgentThread,
  clearThreadSession,
  createAgentThread,
  followAgentTurn,
  formatThreadEvent,
  getAgentThread,
  interruptAgentTurn,
  listAgentThreads,
  presentThread,
  readThreadSession,
  startAgentTurn,
  type ThreadProjection,
  type ThreadSnapshot,
  writeThreadSession
} from "../agentThread";
import { apiGet } from "../api/client";
import type { RunObservability } from "../components/observability/AgentFlightRecorder";
import type { Copy } from "../i18n/messages";
import { createClientIdempotencyKey } from "../lib/ids";
import { reportBlocksFromRun } from "../lib/report";
import { isRecord, stringOrUndefined } from "../lib/values";
import type { AgentRun } from "../types";

export function useAgentWorkbench({
  t,
  onError,
  onTurnCompleted
}: {
  t: Copy;
  onError: (error: unknown) => void;
  onTurnCompleted: () => Promise<void>;
}) {
  const [prompt, setPrompt] = useState(t.prompt);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [threadSnapshot, setThreadSnapshot] = useState<ThreadSnapshot | null>(null);
  const [threadCursor, setThreadCursor] = useState(0);
  const [threadConnection, setThreadConnection] = useState("idle");
  const [partialAnswer, setPartialAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [agentProgress, setAgentProgress] = useState<string[]>([]);
  const [showRawMarkdown, setShowRawMarkdown] = useState(false);
  const [runObservability, setRunObservability] = useState<RunObservability | null>(null);
  const [observabilityLoading, setObservabilityLoading] = useState(false);
  const [threads, setThreads] = useState<ThreadProjection[]>([]);
  const [threadsOpen, setThreadsOpen] = useState(false);
  const [threadsLoading, setThreadsLoading] = useState(false);

  const activeTurnRequest = useRef<{
    threadId: string;
    prompt: string;
    clientMessageId: string;
  } | null>(null);

  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const loadRunObservability = useCallback(async (runId: string) => {
    if (!runId) return;
    setObservabilityLoading(true);
    try {
      const obs = await apiGet<RunObservability>(
        `/api/agent/runs/${encodeURIComponent(runId)}/observability`
      );
      setRunObservability(obs);
    } catch {
      setRunObservability(null);
    } finally {
      setObservabilityLoading(false);
    }
  }, []);

  const followCanonicalTurn = useCallback(
    async (threadId: string, turnId: string, after: number) => {
      setThreadConnection("streaming");
      const result = await followAgentTurn({
        threadId,
        turnId,
        after,
        onCursor: (cursor) => {
          setThreadCursor(cursor);
          writeThreadSession(window.localStorage, { threadId, cursor });
        },
        onReconnecting: (attempt) => {
          setThreadConnection(`reconnecting:${attempt}`);
        },
        onEvent: (event) => {
          setAgentProgress((items) => [...items.slice(-8), formatThreadEvent(event)]);
          if (event.event_type === "agent_message.delta" && isRecord(event.payload.content)) {
            const delta = stringOrUndefined(event.payload.content.text);
            if (delta) setPartialAnswer((value) => `${value}${delta}`);
          }
        }
      });
      setThreadSnapshot(result.snapshot);
      setThreadCursor(result.cursor);
      setPartialAnswer("");
      setThreadConnection("idle");
      writeThreadSession(window.localStorage, { threadId, cursor: result.cursor });
      activeTurnRequest.current = null;
      const missionId = result.snapshot.turns.at(-1)?.mission_id;
      if (missionId) {
        void loadRunObservability(missionId);
      }
    },
    [loadRunObservability]
  );

  // Restore saved thread pointer on mount ONLY if localStorage already holds one.
  useEffect(() => {
    const pointer = readThreadSession(window.localStorage);
    if (!pointer) return;
    let cancelled = false;
    void (async () => {
      try {
        const snapshot = await getAgentThread(pointer.threadId);
        if (cancelled) return;
        if (snapshot.thread.status !== "active") {
          clearThreadSession(window.localStorage);
          return;
        }
        setThreadSnapshot(snapshot);
        setThreadCursor(Math.max(pointer.cursor, snapshot.thread.event_cursor));
        if (snapshot.thread.active_turn_id) {
          setBusy(true);
          await followCanonicalTurn(
            snapshot.thread.thread_id,
            snapshot.thread.active_turn_id,
            pointer.cursor
          );
        }
      } catch (error) {
        if (!cancelled) {
          clearThreadSession(window.localStorage);
          onErrorRef.current(error);
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [followCanonicalTurn]);

  const handleRun = useCallback(async () => {
    const submittedPrompt = prompt.trim();
    if (!submittedPrompt) return;
    setBusy(true);
    setAgentProgress([]);
    setRun(null);
    setRunObservability(null);
    setPartialAnswer("");
    try {
      let snapshot = threadSnapshot;
      if (!snapshot || snapshot.thread.status !== "active") {
        snapshot = await createAgentThread();
        setThreadSnapshot(snapshot);
        setThreadCursor(snapshot.thread.event_cursor);
        writeThreadSession(window.localStorage, {
          threadId: snapshot.thread.thread_id,
          cursor: snapshot.thread.event_cursor
        });
      }
      const threadId = snapshot.thread.thread_id;
      const existing = activeTurnRequest.current;
      const request =
        existing && existing.threadId === threadId && existing.prompt === submittedPrompt
          ? existing
          : {
              threadId,
              prompt: submittedPrompt,
              clientMessageId: createClientIdempotencyKey("web_turn")
            };
      activeTurnRequest.current = request;
      const started = await startAgentTurn(threadId, submittedPrompt, request.clientMessageId);
      setPrompt("");
      const accepted = await getAgentThread(threadId);
      setThreadSnapshot(accepted);
      setThreadCursor(started.event_cursor);
      writeThreadSession(window.localStorage, { threadId, cursor: started.event_cursor });
      await followCanonicalTurn(threadId, started.turn.turn_id, started.event_cursor);
      await onTurnCompleted();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }, [followCanonicalTurn, onError, onTurnCompleted, prompt, threadSnapshot]);

  // Non-destructive: creates a new thread without archiving previous threads.
  const handleNewThread = useCallback(async () => {
    if (threadSnapshot?.thread.active_turn_id) {
      onError(new Error(t.errorConflict));
      return;
    }
    setBusy(true);
    try {
      const created = await createAgentThread();
      setThreadSnapshot(created);
      setThreadCursor(created.thread.event_cursor);
      setAgentProgress([]);
      setRun(null);
      setRunObservability(null);
      setPartialAnswer("");
      activeTurnRequest.current = null;
      writeThreadSession(window.localStorage, {
        threadId: created.thread.thread_id,
        cursor: created.thread.event_cursor
      });
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }, [onError, t.errorConflict, threadSnapshot]);

  const handleArchiveThread = useCallback(async () => {
    if (!threadSnapshot || threadSnapshot.thread.active_turn_id) return;
    setBusy(true);
    try {
      const archived = await archiveAgentThread(threadSnapshot.thread.thread_id);
      setThreadSnapshot(archived);
      clearThreadSession(window.localStorage);
      activeTurnRequest.current = null;
      setThreadConnection("archived");
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }, [onError, threadSnapshot]);

  const handleInterruptTurn = useCallback(async () => {
    const threadId = threadSnapshot?.thread.thread_id;
    const turnId = threadSnapshot?.thread.active_turn_id;
    if (!threadId || !turnId) return;
    try {
      await interruptAgentTurn(threadId, turnId);
      const refreshed = await getAgentThread(threadId);
      setThreadSnapshot(refreshed);
      setThreadCursor(refreshed.thread.event_cursor);
      setThreadConnection("idle");
      activeTurnRequest.current = null;
    } catch (error) {
      onError(error);
    }
  }, [onError, threadSnapshot]);

  const handleToggleThreads = useCallback(async () => {
    const nextOpen = !threadsOpen;
    setThreadsOpen(nextOpen);
    if (!nextOpen) return;
    setThreadsLoading(true);
    try {
      const payload = await listAgentThreads({ limit: 20 });
      setThreads(Array.isArray(payload.items) ? payload.items : []);
    } catch (error) {
      onError(error);
    } finally {
      setThreadsLoading(false);
    }
  }, [onError, threadsOpen]);

  const handleSelectThread = useCallback(
    async (threadId: string) => {
      setThreadsOpen(false);
      setBusy(true);
      setRun(null);
      setPartialAnswer("");
      try {
        const snapshot = await getAgentThread(threadId);
        setThreadSnapshot(snapshot);
        setThreadCursor(snapshot.thread.event_cursor);
        writeThreadSession(window.localStorage, {
          threadId: snapshot.thread.thread_id,
          cursor: snapshot.thread.event_cursor
        });
        const latestMissionId = snapshot.turns.at(-1)?.mission_id;
        if (latestMissionId) {
          void loadRunObservability(latestMissionId);
        } else {
          setRunObservability(null);
        }
      } catch (error) {
        onError(error);
      } finally {
        setBusy(false);
      }
    },
    [loadRunObservability, onError]
  );

  const handleSelectRun = useCallback(
    async (runId: string) => {
      try {
        const loaded = await apiGet<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}`);
        setRun(loaded);
      } catch (error) {
        onError(error);
      }
      await loadRunObservability(runId);
    },
    [loadRunObservability, onError]
  );

  const threadPresentation = useMemo(() => presentThread(threadSnapshot), [threadSnapshot]);
  const reportMarkdown =
    run?.report_markdown || partialAnswer || threadPresentation.answer || "";
  const reportBlocks = useMemo(
    () => (run ? reportBlocksFromRun(run) : []),
    [run]
  );

  return {
    prompt,
    setPrompt,
    run,
    threadSnapshot,
    threadCursor,
    threadConnection,
    busy,
    agentProgress,
    showRawMarkdown,
    setShowRawMarkdown,
    runObservability,
    observabilityLoading,
    threads,
    threadsOpen,
    threadsLoading,
    threadPresentation,
    reportMarkdown,
    reportBlocks,
    handleRun,
    handleNewThread,
    handleArchiveThread,
    handleInterruptTurn,
    handleToggleThreads,
    handleSelectThread,
    handleSelectRun
  };
}

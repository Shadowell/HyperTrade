import {
  Archive,
  Bot,
  History,
  RefreshCw,
  Sparkles,
  Square
} from "lucide-react";
import type { KeyboardEvent } from "react";
import type { ThreadProjection } from "../../agentThread";
import type { Copy } from "../../i18n/messages";
import { statusLabel } from "../../lib/format";
import type { AccessMode } from "../../types";
import { InlineAlert } from "../ui/InlineAlert";

export type ThreadMeta = { id: string; cursor: number; reconnecting: boolean };

export function RunControls({
  t,
  prompt,
  onPromptChange,
  busy,
  turnActive,
  hasThread,
  access,
  thread,
  error,
  onRun,
  onNewThread,
  onArchiveThread,
  onInterruptTurn,
  threads,
  threadsOpen = false,
  threadsLoading = false,
  onToggleThreads,
  onSelectThread
}: {
  t: Copy;
  prompt: string;
  onPromptChange: (value: string) => void;
  busy: boolean;
  turnActive: boolean;
  hasThread: boolean;
  access: AccessMode;
  thread: ThreadMeta | null;
  error: string;
  onRun: () => void;
  onNewThread: () => void;
  onArchiveThread: () => void;
  onInterruptTurn?: () => void;
  threads?: ThreadProjection[];
  threadsOpen?: boolean;
  threadsLoading?: boolean;
  onToggleThreads?: () => void;
  onSelectThread?: (threadId: string) => void;
}) {
  // Without an admin session privileged actions are refused, so indicate read-only mode upfront.
  const readonly = access === "readonly";
  const quickCommands = [
    { label: t.quickCmdEvolutionLabel, prompt: t.quickCmdEvolutionPrompt },
    { label: t.quickCmdPaperLabel, prompt: t.quickCmdPaperPrompt },
    { label: t.quickCmdStrategyLabel, prompt: t.quickCmdStrategyPrompt },
    { label: t.quickCmdCognitiveLabel, prompt: t.quickCmdCognitivePrompt }
  ];

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      if (readonly || busy || turnActive) return;
      event.preventDefault();
      onRun();
    }
  }

  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="section-title">{t.runConsole}</h2>
          <p className="mt-1 text-sm text-ink/55">{t.runConsoleHint}</p>
        </div>
        <Sparkles size={18} className="text-accent" />
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {quickCommands.map((chip) => (
          <button
            className="rounded-full border border-ink/15 bg-paper px-2.5 py-1 text-xs font-medium text-ink/75 transition hover:border-accent/50 hover:text-ink"
            key={chip.label}
            onClick={() => onPromptChange(chip.prompt)}
            type="button"
          >
            {chip.label}
          </button>
        ))}
      </div>

      <label className="sr-only" htmlFor="agent-prompt">
        {t.promptLabel}
      </label>
      <textarea
        className="prompt-box"
        id="agent-prompt"
        onChange={(event) => onPromptChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t.promptPlaceholder}
        value={prompt}
      />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          className="button-primary"
          disabled={readonly || busy || turnActive}
          onClick={onRun}
          type="button"
        >
          {busy ? <RefreshCw className="animate-spin" size={16} /> : <Bot size={16} />}
          {t.run}
        </button>
        {turnActive && onInterruptTurn ? (
          <button
            className="icon-button border-danger/35 text-danger"
            disabled={readonly}
            onClick={onInterruptTurn}
            type="button"
          >
            <Square size={13} />
            {t.interruptTurn}
          </button>
        ) : null}
        <button
          className="icon-button"
          disabled={readonly || busy}
          onClick={onNewThread}
          type="button"
        >
          {t.newThread}
        </button>
        <button
          className="icon-button"
          disabled={readonly || busy || !hasThread || turnActive}
          onClick={onArchiveThread}
          type="button"
        >
          <Archive size={14} />
          {t.archiveThread}
        </button>
        {onToggleThreads ? (
          <button
            aria-expanded={threadsOpen}
            className="icon-button ml-auto"
            disabled={readonly}
            onClick={onToggleThreads}
            type="button"
          >
            <History size={14} />
            {t.threadSwitcher}
          </button>
        ) : null}
      </div>

      {threadsOpen && onSelectThread ? (
        <div className="mt-3 rounded-xl border border-ink/15 bg-paper p-3">
          {threadsLoading ? (
            <div className="text-xs text-ink/55">{t.overviewLoading}…</div>
          ) : !threads || threads.length === 0 ? (
            <div className="text-xs text-ink/55">{t.noThreads}</div>
          ) : (
            <div className="max-h-44 space-y-1.5 overflow-auto">
              {threads.map((item) => (
                <button
                  className={`flex w-full items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-left text-xs transition ${
                    thread?.id === item.thread_id
                      ? "border-accent/50 bg-accent/10 text-ink"
                      : "border-ink/10 text-ink/75 hover:border-accent/35"
                  }`}
                  key={item.thread_id}
                  onClick={() => onSelectThread(item.thread_id)}
                  type="button"
                >
                  <span className="min-w-0 truncate font-mono">
                    {item.title || item.thread_id} · {item.thread_id}
                  </span>
                  <span className="shrink-0 text-[11px] text-ink/55">
                    {statusLabel(item.status)} · #{item.event_cursor}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : null}

      {readonly ? (
        <InlineAlert role="note" title={t.readOnlyTitle} tone="brass">
          {t.readOnlyHint}
        </InlineAlert>
      ) : null}
      {thread ? (
        <div className="mt-3 flex flex-wrap gap-2 font-mono text-xs text-ink/55">
          <span>{thread.id}</span>
          <span>cursor={thread.cursor}</span>
          <span>{thread.reconnecting ? t.reconnecting : t.threadReady}</span>
        </div>
      ) : null}
      {error ? (
        <InlineAlert role="alert" tone="danger">
          {error}
        </InlineAlert>
      ) : null}
    </>
  );
}

import {
  Archive,
  Bot,
  RefreshCw,
  Sparkles
} from "lucide-react";
import type { Copy } from "../../i18n/messages";
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
  onArchiveThread
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
}) {
  // Without an admin session every one of these calls is refused, so say so up front instead of
  // letting the operator press the primary button and read a raw "Not authenticated".
  const readonly = access === "readonly";
  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="section-title">{t.runConsole}</h2>
          <p className="mt-1 text-sm text-ink/50">{t.runConsoleHint}</p>
        </div>
        <Sparkles size={18} className="text-brass" />
      </div>
      <label className="sr-only" htmlFor="agent-prompt">
        {t.promptLabel}
      </label>
      <textarea
        className="prompt-box"
        id="agent-prompt"
        onChange={(event) => onPromptChange(event.target.value)}
        value={prompt}
      />
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="button-primary"
          disabled={readonly || busy || turnActive}
          onClick={onRun}
          type="button"
        >
          {busy ? <RefreshCw className="animate-spin" size={16} /> : <Bot size={16} />}
          {t.run}
        </button>
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
      </div>
      {readonly ? (
        <InlineAlert role="note" title={t.readOnlyTitle} tone="brass">
          {t.readOnlyHint}
        </InlineAlert>
      ) : null}
      {thread ? (
        <div className="mt-3 flex flex-wrap gap-2 font-mono text-xs text-ink/50">
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

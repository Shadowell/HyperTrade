import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  Loader2
} from "lucide-react";
import type { Copy } from "../../i18n/messages";
import { useNow } from "../../hooks/useNow";
import { formatRelativeAge, formatTimestamp } from "../../lib/time";
import type { AccessMode, Language } from "../../types";

/** Where the runtime overview stands: it is never "ready" on made-up data. */
export type SyncState = "connecting" | "ready" | "unavailable";

export function HarnessHeader({
  t,
  language,
  sync,
  generatedAt,
  refreshing,
  access
}: {
  t: Copy;
  language: Language;
  sync: SyncState;
  generatedAt: string | null;
  refreshing: boolean;
  access: AccessMode;
}) {
  const now = useNow();
  const syncedAt = formatTimestamp(generatedAt, language);
  const ageSeconds =
    now !== null && generatedAt ? (now - new Date(generatedAt).getTime()) / 1000 : null;
  const status =
    sync === "ready"
      ? { label: t.healthy, icon: <CheckCircle2 className="text-signal" size={18} /> }
      : sync === "unavailable"
        ? { label: t.overviewUnavailable, icon: <AlertTriangle className="text-danger" size={18} /> }
        : { label: t.overviewConnecting, icon: <Loader2 className="animate-spin text-brass" size={18} /> };

  return (
    <header
      className="grid grid-cols-[1fr_auto] items-start gap-4 border-b border-ink/15 pb-5 max-md:grid-cols-1"
      id="harness"
    >
      <div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase text-brass">
          <span>{t.risk}</span>
          <span className="h-1 w-1 rounded-full bg-brass/45" />
          <span>{sync === "ready" ? t.lastSync : status.label}</span>
        </div>
        <h1 className="mt-2 text-4xl font-semibold tracking-tight max-sm:text-3xl">
          {t.workbenchTitle}
        </h1>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-ink/55">
          <span>{t.workbenchSubtitle}</span>
          {syncedAt && generatedAt ? (
            <time className="font-mono" dateTime={generatedAt}>
              {syncedAt}
              {ageSeconds !== null && ageSeconds >= 0 ? ` · ${formatRelativeAge(ageSeconds, language)}` : ""}
            </time>
          ) : null}
          {refreshing ? (
            <span className="inline-flex items-center gap-2 text-brass">
              <span className="skeleton-pulse h-1.5 w-1.5 rounded-full bg-brass" />
              {t.overviewLoading}
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex flex-col items-end gap-2 max-md:items-start">
        <div className="runtime-pill">
          <div>
            <span>{t.systemStatus}</span>
            <strong>{status.label}</strong>
            <span className="mt-1 font-mono">{t.okx}</span>
          </div>
          {status.icon}
        </div>
        <AccessBadge access={access} t={t} />
      </div>
    </header>
  );
}

/** Shown only after a privileged call was refused; the console never probes the session. */
function AccessBadge({ access, t }: { access: AccessMode; t: Copy }) {
  if (access !== "readonly") return null;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded border border-brass/30 px-2 py-1 text-xs font-semibold text-brass"
      title={t.readOnlyHint}
    >
      <Eye size={12} />
      {t.readOnlyBadge}
    </span>
  );
}

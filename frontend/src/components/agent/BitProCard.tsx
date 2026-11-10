import type { Copy } from "../../i18n/messages";
import { formatMetricNumber, formatTokenSource } from "../../lib/format";
import type { HarnessOverview } from "../../types";
import { StatusDot } from "../ui/StatusDot";

type BitPro = NonNullable<HarnessOverview["bitpro"]>;

/** How this console reaches BitPro: contract endpoints only, never BitPro business logic. */
export function BitProCard({ t, bitpro }: { t: Copy; bitpro: BitPro }) {
  return (
    <div className="mt-6 rounded-md border border-ink/10 bg-paper/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{t.bitproMcp}</h3>
          <p className="mt-1 text-xs leading-5 text-ink/50">{t.bitproMcpHint}</p>
        </div>
        <span
          className={`inline-flex items-center gap-2 rounded border px-2 py-1 text-xs font-semibold ${
            bitpro.token_configured
              ? "border-signal/25 text-signal"
              : "border-danger/25 text-danger"
          }`}
        >
          <StatusDot enabled={bitpro.token_configured} />
          {bitpro.token_configured ? t.mcpTokenReady : t.mcpTokenMissing}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 max-md:grid-cols-1">
        <div className="mini-block">
          <span>{t.mcpApiBase}</span>
          <strong className="truncate font-mono">{bitpro.api_base}</strong>
        </div>
        <div className="mini-block">
          <span>{t.mcpAuthHeader}</span>
          <strong className="truncate font-mono">{bitpro.auth_header}</strong>
        </div>
        <div className="mini-block">
          <span>{t.mcpTokenSource}</span>
          <strong>{formatTokenSource(bitpro.token_source, t)}</strong>
        </div>
        <div className="mini-block">
          <span>{t.mcpScopes}</span>
          <strong className="font-mono">
            {Object.keys(bitpro.agent_auth?.scope_classes ?? {}).join(" / ") || "R / W / L / T"}
          </strong>
        </div>
        <div className="mini-block">
          <span>{t.mcpAdapter}</span>
          <strong className="truncate font-mono">{bitpro.adapter}</strong>
        </div>
        <div className="mini-block">
          <span>{t.mcpTools}</span>
          <strong className="font-mono">{formatMetricNumber(bitpro.tools.length)}</strong>
        </div>
      </div>
    </div>
  );
}

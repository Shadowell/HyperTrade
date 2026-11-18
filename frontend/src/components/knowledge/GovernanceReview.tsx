import { CheckCircle2 } from "lucide-react";
import type { Copy } from "../../i18n/messages";
import { statusLabel } from "../../lib/format";
import type { AccessMode, MemoryAssertion, SkillProposal, SkillRelease } from "../../types";

export function GovernanceReview({
  assertions,
  proposals,
  releases,
  reason,
  setReason,
  onDecision,
  access,
  t
}: {
  assertions: MemoryAssertion[];
  proposals: SkillProposal[];
  releases: SkillRelease[];
  reason: string;
  setReason: (value: string) => void;
  onDecision: (
    resource: "assertion" | "skill",
    resourceId: string,
    decision: "approve" | "reject" | "dispute"
  ) => Promise<void>;
  access: AccessMode;
  t: Copy;
}) {
  const pendingAssertions = assertions.filter((item) =>
    ["proposed", "disputed"].includes(item.status)
  );
  const pendingSkills = proposals.filter((item) => item.status === "pending_approval");
  const actionDisabled = access === "readonly" || !reason.trim();

  return (
    <section className="panel" aria-labelledby="governance-review-title">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="section-title" id="governance-review-title">
            {t.governanceReview}
          </h2>
          <p className="mt-1 text-sm text-ink/55">{t.governanceReviewHint}</p>
        </div>
        <CheckCircle2 className="text-signal" size={18} />
      </div>
      <input
        aria-label={t.governanceReason}
        className="field-light mt-4 w-full"
        onChange={(event) => setReason(event.target.value)}
        placeholder={t.governanceReason}
        value={reason}
      />
      <div className="mt-4 grid grid-cols-2 gap-4 max-xl:grid-cols-1">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase text-ink/55">
            {t.memoryAssertions} · {pendingAssertions.length}
          </div>
          <div className="space-y-2">
            {pendingAssertions.length === 0 ? (
              <div className="empty-row">{t.noAssertions}</div>
            ) : (
              pendingAssertions.slice(0, 10).map((item) => (
                <div className="operator-card block" data-tone="brass" key={item.id}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-xs text-ink/55">{item.id}</span>
                    <span className="text-xs text-brass">{statusLabel(item.status)}</span>
                  </div>
                  <p className="mt-2 text-sm">{item.claim}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      className="icon-button"
                      disabled={actionDisabled}
                      onClick={() => void onDecision("assertion", item.id, "approve")}
                      type="button"
                    >
                      {t.approve}
                    </button>
                    <button
                      className="icon-button"
                      disabled={actionDisabled}
                      onClick={() => void onDecision("assertion", item.id, "dispute")}
                      type="button"
                    >
                      {t.dispute}
                    </button>
                    <button
                      className="icon-button"
                      disabled={actionDisabled}
                      onClick={() => void onDecision("assertion", item.id, "reject")}
                      type="button"
                    >
                      {t.reject}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold uppercase text-ink/55">
            {t.skillProposals} · {pendingSkills.length}
          </div>
          <div className="space-y-2">
            {pendingSkills.length === 0 ? (
              <div className="empty-row">{t.noSkillProposals}</div>
            ) : (
              pendingSkills.slice(0, 10).map((item) => (
                <div className="operator-card block" data-tone="violet" key={item.id}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <strong>{item.skill_key}</strong>
                    <span className="font-mono text-xs text-ink/55">
                      {item.definition_hash.slice(0, 12)}
                    </span>
                  </div>
                  <div className="mt-2 font-mono text-xs text-ink/55">{item.id}</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      className="icon-button"
                      disabled={actionDisabled}
                      onClick={() => void onDecision("skill", item.id, "approve")}
                      type="button"
                    >
                      {t.approve}
                    </button>
                    <button
                      className="icon-button"
                      disabled={actionDisabled}
                      onClick={() => void onDecision("skill", item.id, "reject")}
                      type="button"
                    >
                      {t.reject}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="mb-2 mt-4 text-xs font-semibold uppercase text-ink/55">
            {t.skillReleases} · {releases.length}
          </div>
          <div className="flex flex-wrap gap-2">
            {releases.length === 0 ? (
              <div className="empty-row w-full">{t.noSkillReleases}</div>
            ) : (
              releases.slice(0, 10).map((release) => (
                <span className="evidence-chip" key={release.id}>
                  {release.skill_key} v{release.version} · {statusLabel(release.status)}
                </span>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

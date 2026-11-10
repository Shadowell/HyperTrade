import type { ReactNode } from "react";

const TONES = {
  danger: "border-danger/30 bg-danger/5 text-danger",
  brass: "border-brass/30 bg-brass/5 text-brass",
  signal: "border-signal/30 bg-signal/5 text-signal"
} as const;

/**
 * `role="alert"` interrupts a screen reader and is for failures; `status` and `note` are polite.
 */
export function InlineAlert({
  tone,
  role = "status",
  title,
  children
}: {
  tone: keyof typeof TONES;
  role?: "alert" | "status" | "note";
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`mt-3 rounded border px-3 py-2 text-sm ${TONES[tone]}`} role={role}>
      {title ? <strong className="block font-semibold">{title}</strong> : null}
      {children ? <div className={title ? "mt-0.5 text-ink/65" : ""}>{children}</div> : null}
    </div>
  );
}

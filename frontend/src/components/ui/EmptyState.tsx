import type { ReactNode } from "react";

/** An honest "nothing here yet": says what is missing and what makes it appear. */
export function EmptyState({
  title,
  hint,
  action
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-row my-3 flex flex-col items-center gap-1 text-center">
      <strong className="text-sm font-semibold text-ink/70">{title}</strong>
      {hint ? <span className="max-w-md text-xs leading-5 text-ink/50">{hint}</span> : null}
      {action}
    </div>
  );
}

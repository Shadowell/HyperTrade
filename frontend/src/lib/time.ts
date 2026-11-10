import type { Language } from "../types";

const LOCALES: Record<Language, string> = { zh: "zh-CN", en: "en-US" };

/** Local date and time with the zone, e.g. "2026年11月10日 20:52:38 [GMT+8]"; null if unparsable. */
export function formatTimestamp(iso: string | null | undefined, language: Language): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  // Explicit fields rather than dateStyle/timeStyle: those cannot be combined with timeZoneName
  // (Intl throws a TypeError), and an exception here would unmount the whole console.
  return new Intl.DateTimeFormat(LOCALES[language], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short"
  }).format(date);
}

/** "12 seconds ago" / "12 秒前", picking the largest sensible unit. */
export function formatRelativeAge(seconds: number, language: Language): string {
  const rtf = new Intl.RelativeTimeFormat(LOCALES[language], { numeric: "auto" });
  const value = Math.max(0, seconds);
  if (value < 60) return rtf.format(-Math.round(value), "second");
  if (value < 3600) return rtf.format(-Math.round(value / 60), "minute");
  if (value < 86400) return rtf.format(-Math.round(value / 3600), "hour");
  return rtf.format(-Math.round(value / 86400), "day");
}

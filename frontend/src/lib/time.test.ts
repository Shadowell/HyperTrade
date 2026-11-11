import { expect, test } from "vitest";
import { formatRelativeAge, formatTimestamp } from "./time";

test("formats a timestamp together with its zone instead of throwing", () => {
  // Regression: dateStyle/timeStyle cannot be combined with timeZoneName. Intl threw a
  // TypeError while the header rendered and the whole console unmounted (blank page).
  const zh = formatTimestamp("2026-11-10T12:52:38Z", "zh");
  const en = formatTimestamp("2026-11-10T12:52:38Z", "en");

  expect(zh).toMatch(/2026/);
  expect(en).toMatch(/2026/);
  expect(zh).toMatch(/GMT|UTC/);
  expect(en).toMatch(/GMT|UTC/);
});

test("returns null for missing or unparsable input rather than a bogus date", () => {
  expect(formatTimestamp(null, "zh")).toBeNull();
  expect(formatTimestamp(undefined, "en")).toBeNull();
  expect(formatTimestamp("", "en")).toBeNull();
  expect(formatTimestamp("not a date", "zh")).toBeNull();
});

test("relative age picks the largest sensible unit", () => {
  expect(formatRelativeAge(12, "en")).toBe("12 seconds ago");
  expect(formatRelativeAge(120, "en")).toBe("2 minutes ago");
  expect(formatRelativeAge(7200, "en")).toBe("2 hours ago");
  expect(formatRelativeAge(172800, "en")).toBe("2 days ago");
  expect(formatRelativeAge(12, "zh")).toMatch(/12/);
});

test("a negative age (clock skew) is clamped instead of reading as the future", () => {
  expect(formatRelativeAge(-5, "en")).toBe("now");
});

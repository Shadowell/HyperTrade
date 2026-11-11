import { statusOf } from "../api/client";
import type { Copy } from "../i18n/messages";

/**
 * A message an operator can act on. Raw API text such as "Not authenticated" or a bare status
 * code says nothing about what to do next, so the cases the console can recognise are mapped to
 * localized sentences and everything else keeps the server's own message.
 */
export function describeError(error: unknown, t: Copy): string {
  const status = statusOf(error);
  if (status === 401 || status === 403) return t.errorNotAuthenticated;
  if (status === 409) return t.errorConflict;
  // fetch() rejects with a TypeError when the network or the backend is unreachable
  if (error instanceof TypeError) return t.errorNetwork;
  if (error instanceof Error && error.message) return error.message;
  return t.errorGeneric;
}

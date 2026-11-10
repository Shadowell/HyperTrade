import { useCallback, useEffect, useState } from "react";
import { apiGet, isAuthError } from "../api/client";

/**
 * - checking: first /api/auth/me not answered yet
 * - operator: a valid admin session cookie
 * - readonly: the server said 401/403, so privileged actions cannot succeed
 * - unknown: the check itself failed (network): do not block anything, the server decides
 */
export type AccessMode = "checking" | "operator" | "readonly" | "unknown";

export function useSession() {
  const [access, setAccess] = useState<AccessMode>("checking");
  const [username, setUsername] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const me = await apiGet<{ username: string }>("/api/auth/me");
        if (cancelled) return;
        setUsername(me.username);
        setAccess("operator");
      } catch (error) {
        if (cancelled) return;
        setUsername(null);
        setAccess(isAuthError(error) ? "readonly" : "unknown");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** A privileged call was refused: stop offering actions that cannot work. */
  const markReadonly = useCallback(() => {
    setUsername(null);
    setAccess("readonly");
  }, []);

  return { access, username, markReadonly };
}

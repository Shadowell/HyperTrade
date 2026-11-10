/**
 * Minimal typed fetch wrapper for the operator console API.
 *
 * Every request carries the session cookie. A non-2xx response becomes an `ApiError` that keeps
 * the HTTP status and FastAPI's `detail`, so callers can tell "not signed in" (401/403) from
 * "backend down" (network failure) from a real server error instead of showing a raw status code.
 */
import { ThreadProtocolRequestError } from "../agentThread";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // not JSON: fall through to the status text
  }
  return response.statusText || String(response.status);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init });
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

export function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, { ...init, method: "GET" });
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

/** HTTP status carried by any error the console's two request layers can throw, if any. */
export function statusOf(error: unknown): number | undefined {
  if (error instanceof ApiError || error instanceof ThreadProtocolRequestError) {
    return error.status;
  }
  return undefined;
}

/** True when the server refused the request because there is no (valid) admin session. */
export function isAuthError(error: unknown): boolean {
  const status = statusOf(error);
  return status === 401 || status === 403;
}

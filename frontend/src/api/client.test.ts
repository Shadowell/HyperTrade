import { afterEach, expect, test, vi } from "vitest";
import { ThreadProtocolRequestError } from "../agentThread";
import { ApiError, apiGet, apiPost, isAuthError, statusOf } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

function respond(body: unknown, status = 200, statusText = ""): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => body
  } as Response;
}

test("apiGet sends the session cookie and returns the parsed JSON", async () => {
  const fetchMock = vi.fn(async () => respond({ ok: true }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(apiGet<{ ok: boolean }>("/api/x")).resolves.toEqual({ ok: true });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/x",
    expect.objectContaining({ credentials: "include", method: "GET" })
  );
});

test("a non-2xx response becomes an ApiError with the status and FastAPI's detail", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => respond({ detail: "Not authenticated" }, 401)));

  const error = await apiGet("/api/x").catch((caught: unknown) => caught);

  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).status).toBe(401);
  expect((error as ApiError).message).toBe("Not authenticated");
});

test("a non-JSON error body falls back to the status text, then to the status code", async () => {
  const notJson = {
    ok: false,
    status: 502,
    statusText: "Bad Gateway",
    json: async () => {
      throw new SyntaxError("Unexpected token <");
    }
  } as unknown as Response;
  vi.stubGlobal("fetch", vi.fn(async () => notJson));
  await expect(apiGet("/api/x")).rejects.toMatchObject({ status: 502, message: "Bad Gateway" });

  vi.stubGlobal("fetch", vi.fn(async () => ({ ...notJson, statusText: "" }) as Response));
  await expect(apiGet("/api/x")).rejects.toMatchObject({ status: 502, message: "502" });
});

test("apiPost sends a JSON body with the right header", async () => {
  const fetchMock = vi.fn(async () => respond({ id: 1 }));
  vi.stubGlobal("fetch", fetchMock);

  await apiPost("/api/y", { a: 1 });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/y",
    expect.objectContaining({
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a: 1 })
    })
  );
});

test("a network failure is not an auth error and carries no status", () => {
  const failure = new TypeError("Failed to fetch");
  expect(statusOf(failure)).toBeUndefined();
  expect(isAuthError(failure)).toBe(false);
});

test("both request layers' errors are recognised as auth errors for 401 and 403 only", () => {
  expect(isAuthError(new ApiError(401, "x"))).toBe(true);
  expect(isAuthError(new ApiError(403, "x"))).toBe(true);
  expect(isAuthError(new ThreadProtocolRequestError("x", 401))).toBe(true);
  expect(isAuthError(new ApiError(404, "x"))).toBe(false);
  expect(isAuthError(new ThreadProtocolRequestError("x", 409))).toBe(false);
});

import { expect, test } from "vitest";
import { ThreadProtocolRequestError } from "../agentThread";
import { ApiError } from "../api/client";
import { copy } from "../i18n/messages";
import { describeError } from "./errors";

const t = copy.zh;

test("a refused request (401/403) says an admin session is needed", () => {
  expect(describeError(new ApiError(401, "Not authenticated"), t)).toBe(t.errorNotAuthenticated);
  expect(describeError(new ApiError(403, "Forbidden"), t)).toBe(t.errorNotAuthenticated);
  // the thread protocol layer throws its own error class; it must be recognised too
  expect(describeError(new ThreadProtocolRequestError("Not authenticated", 401), t)).toBe(
    t.errorNotAuthenticated
  );
});

test("a conflict explains that a turn is already running", () => {
  expect(describeError(new ThreadProtocolRequestError("Turn active", 409), t)).toBe(t.errorConflict);
});

test("a rejected fetch (TypeError) is reported as an unreachable backend", () => {
  expect(describeError(new TypeError("Failed to fetch"), t)).toBe(t.errorNetwork);
});

test("anything else keeps the server's own message, and falls back when there is none", () => {
  expect(describeError(new ApiError(500, "database is down"), t)).toBe("database is down");
  expect(describeError(new Error("boom"), t)).toBe("boom");
  expect(describeError(new Error(""), t)).toBe(t.errorGeneric);
  expect(describeError("weird", t)).toBe(t.errorGeneric);
});

test("the English copy is used when the console language is English", () => {
  expect(describeError(new ApiError(401, "x"), copy.en)).toBe(copy.en.errorNotAuthenticated);
  expect(copy.en.errorNotAuthenticated).not.toBe(copy.zh.errorNotAuthenticated);
});

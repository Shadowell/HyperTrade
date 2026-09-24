import { describe, expect, it } from "vitest";
import { DEFAULT_API_BASE, resolveSavedApiBase } from "./bridge";

describe("resolveSavedApiBase", () => {
  it("uses the new server for an empty or legacy saved address", () => {
    expect(resolveSavedApiBase(null)).toBe(DEFAULT_API_BASE);
    expect(resolveSavedApiBase("http://47.79.36.92:3333")).toBe(DEFAULT_API_BASE);
    expect(resolveSavedApiBase("http://47.79.36.92:3333/")).toBe(DEFAULT_API_BASE);
  });

  it("preserves a user-selected server", () => {
    expect(resolveSavedApiBase("https://custom.example/api")).toBe("https://custom.example/api");
  });
});

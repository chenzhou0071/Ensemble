import { beforeEach, describe, expect, it } from "vitest";

import { getClientId } from "../client";

beforeEach(() => localStorage.clear());

describe("getClientId", () => {
  it("generates and persists a hex id", () => {
    const first = getClientId();
    expect(first).toMatch(/^[0-9a-f]{32}$/);
    expect(getClientId()).toBe(first);                 // 再次调用：复用持久化值
    expect(localStorage.getItem("ensemble.client_id")).toBe(first);
  });

  it("reuses a pre-existing client id", () => {
    localStorage.setItem("ensemble.client_id", "abc123");
    expect(getClientId()).toBe("abc123");
  });
});

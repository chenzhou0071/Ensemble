import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../rest";

afterEach(() => vi.unstubAllGlobals());

describe("rest", () => {
  it("GETs modules and parses json", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => [{ id: "m", title: "M" }],
    });
    vi.stubGlobal("fetch", fetchMock);
    const mods = await api.modules();
    expect(fetchMock).toHaveBeenCalledWith("/api/modules", undefined);
    expect(mods[0].id).toBe("m");
  });

  it("POSTs create campaign with json body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ campaign_id: "c1" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await api.createCampaign("misty_hollow", "初探", "张三", "client-1");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock.mock.calls[0][0]).toBe("/api/campaigns");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      module_id: "misty_hollow", title: "初探", player_name: "张三",
      client_id: "client-1",
    });
  });

  it("GETs campaign list scoped by client_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    await api.campaigns("client-1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/campaigns?client_id=client-1");
  });

  it("throws on non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 404, text: async () => "not found",
    }));
    await expect(api.modules()).rejects.toThrow("404");
  });
});

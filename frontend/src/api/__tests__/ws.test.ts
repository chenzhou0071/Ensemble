import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WsClient } from "../ws";

class FakeWS {
  static instances: FakeWS[] = [];
  static OPEN = 1;
  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];
  constructor(url: string) {
    this.url = url;
    FakeWS.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

beforeEach(() => {
  FakeWS.instances = [];
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function makeClient() {
  const events: unknown[] = [];
  const client = new WsClient("c1", "p1", {
    onEvent: (e) => events.push(e),
    onStatus: () => {},
  });
  client.connect();
  return { client, events };
}

describe("WsClient", () => {
  it("connects with resume_from and forwards seq tracked events", () => {
    const { client, events } = makeClient();
    const ws = FakeWS.instances[0];
    expect(ws.url).toContain("/ws/campaign/c1?player_id=p1&resume_from=0");
    ws.readyState = 1;
    ws.onmessage!({
      data: JSON.stringify({ seq: 5, type: "token", visibility: "all",
                             payload: { speaker: "gm", text: "x" } }),
    });
    expect(events).toHaveLength(1);
    client.close();
  });

  it("reconnects with updated resume_from after close", () => {
    const { client } = makeClient();
    const first = FakeWS.instances[0];
    first.readyState = 1;
    first.onmessage!({
      data: JSON.stringify({ seq: 7, type: "turn", visibility: "all",
                             payload: { phase: "collecting", turn_id: 1 } }),
    });
    first.onclose!();                                    // 服务端断开
    vi.advanceTimersByTime(1500);                        // 越过首次退避
    expect(FakeWS.instances).toHaveLength(2);
    expect(FakeWS.instances[1].url).toContain("resume_from=7");
    client.close();
  });

  it("sendInput sends json input frame only when open", () => {
    const { client } = makeClient();
    const ws = FakeWS.instances[0];
    client.sendInput("我进门");                          // 未 open：丢弃
    expect(ws.sent).toHaveLength(0);
    ws.readyState = 1;
    client.sendInput("我进门");
    expect(JSON.parse(ws.sent[0])).toEqual({ type: "input", text: "我进门" });
    client.close();
  });
});

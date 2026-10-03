import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Room from "../Room";
import { useGame } from "../../stores/game";

const handlers: { onEvent?: (e: unknown) => void; onStatus?: (s: string) => void } = {};
const clientMock = { connect: vi.fn(), close: vi.fn(), sendInput: vi.fn() };

vi.mock("../../api/ws", () => ({
  WsClient: vi.fn().mockImplementation((_c: string, _p: string, h: typeof handlers) => {
    handlers.onEvent = h.onEvent as never;
    handlers.onStatus = h.onStatus as never;
    return clientMock;
  }),
}));
vi.mock("../../api/rest", () => ({
  api: {
    module: vi.fn().mockResolvedValue({
      id: "misty_hollow", title: "迷雾幽谷",
      npcs: [{ id: "elder", name: "村长" }], endings: [],
    }),
  },
}));

const SESSION = { campaignId: "c1", playerId: "p1", title: "测试局" };

beforeEach(() => {
  vi.clearAllMocks();
  useGame.getState().reset();
});

describe("Room", () => {
  it("renders streamed narration resolving npc names", async () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    act(() => {
      handlers.onStatus!("open");
      handlers.onEvent!({ seq: 1, type: "token", visibility: "all",
                          payload: { speaker: "gm", text: "雾气涌来。" } });
      handlers.onEvent!({ seq: 2, type: "token", visibility: "all",
                          payload: { speaker: "npc:elder", text: "别去磨坊。" } });
    });
    expect(await screen.findByText("雾气涌来。")).toBeInTheDocument();
    expect(await screen.findByText("【村长】")).toBeInTheDocument();
    expect(clientMock.connect).toHaveBeenCalled();
  });

  it("disables input until collecting phase", () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    act(() => handlers.onStatus!("open"));
    expect(screen.getByPlaceholderText("GM 正在处理本回合…")).toBeDisabled();
    act(() => handlers.onEvent!({ seq: 1, type: "turn", visibility: "all",
                                  payload: { phase: "collecting", turn_id: 1 } }));
    expect(screen.getByPlaceholderText("输入你的行动（回车提交）")).toBeEnabled();
  });
});

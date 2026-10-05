import { act, fireEvent, render, screen, within } from "@testing-library/react";
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

  it("shows current scene name in sidebar between character and npc panels", () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    act(() => {
      handlers.onEvent!({ seq: 1, type: "scene", visibility: "all",
                          payload: { scene_id: "square", name: "镇中心广场",
                                     description: "石砌广场。", npcs: [] } });
    });
    const side = screen.getByRole("complementary");
    expect(within(side).getByText("镇中心广场")).toBeInTheDocument();
    const headings = [...side.querySelectorAll("h3")].map((h) => h.textContent);
    expect(headings).toEqual(["角色", "所在位置", "已结识人物", "线索（0）", "检定记录"]);
  });

  it("disables input until collecting phase", () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    act(() => handlers.onStatus!("open"));
    expect(screen.getByPlaceholderText("GM 正在处理本回合…")).toBeDisabled();
    act(() => handlers.onEvent!({ seq: 1, type: "turn", visibility: "all",
                                  payload: { phase: "collecting", turn_id: 1 } }));
    expect(screen.getByPlaceholderText("输入你的行动（回车提交）")).toBeEnabled();
  });

  it("shows story ending in narration without a popup overlay", () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    act(() => {
      handlers.onStatus!("open");
      handlers.onEvent!({ seq: 1, type: "turn", visibility: "all",
                          payload: { phase: "ended", ending_reached: "ending_break" } });
    });
    expect(screen.queryByText("故事已抵达结局")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("故事已结束")).toBeDisabled();
  });

  it("opens the mobile drawer via 手账 button and closes it with ✕", () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    const side = screen.getByRole("complementary");
    expect(side.classList.contains("open")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "手账" }));
    expect(side.classList.contains("open")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "关闭手账" }));
    expect(side.classList.contains("open")).toBe(false);
  });

  it("closes the mobile drawer when tapping the scrim", () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "手账" }));
    expect(screen.getByTestId("room-scrim")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("room-scrim"));
    expect(screen.getByRole("complementary").classList.contains("open")).toBe(false);
    expect(screen.queryByTestId("room-scrim")).not.toBeInTheDocument();
  });
});

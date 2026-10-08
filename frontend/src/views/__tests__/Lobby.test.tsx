import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Lobby from "../Lobby";
import { api } from "../../api/rest";

vi.mock("../../api/rest", () => ({
  api: {
    modules: vi.fn(),
    campaigns: vi.fn(),
    createCampaign: vi.fn(),
    campaign: vi.fn(),
  },
}));
vi.mock("../../client", () => ({ getClientId: () => "test-client" }));

const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.modules.mockResolvedValue([
    { id: "misty_hollow", title: "迷雾幽谷", version: "0.1", path: "" },
  ]);
  mocked.campaigns.mockResolvedValue([]);
});

describe("Lobby", () => {
  it("creates a campaign and enters the room", async () => {
    mocked.createCampaign.mockResolvedValue({
      campaign_id: "c1", branch_id: "c1@main",
      player_id: "p1", character_id: "pc_p1",
    });
    const onEnter = vi.fn();
    render(<Lobby onEnter={onEnter} />);
    await screen.findByText("迷雾幽谷");
    await userEvent.type(screen.getByLabelText("战役名"), "夜探听雨楼");
    await userEvent.type(screen.getByLabelText("玩家名"), "沈青");
    await userEvent.click(screen.getByText("开始跑团"));
    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith({
        campaignId: "c1", playerId: "p1", title: "夜探听雨楼",
      }),
    );
    expect(mocked.campaigns).toHaveBeenCalledWith("test-client");
    expect(mocked.createCampaign).toHaveBeenCalledWith(
      "misty_hollow", "夜探听雨楼", "沈青", "test-client");
  });

  it("starts empty and blocks start until both names are filled", async () => {
    render(<Lobby onEnter={vi.fn()} />);
    await screen.findByText("迷雾幽谷");
    const start = screen.getByRole("button", { name: "开始跑团" });
    const title = screen.getByLabelText("战役名");
    const playerName = screen.getByLabelText("玩家名");
    expect(title).toHaveValue("");
    expect(playerName).toHaveValue("");
    expect(start).toBeDisabled();

    await userEvent.type(title, "   ");
    expect(start).toBeDisabled();          // 纯空白不算填写
    await userEvent.clear(title);
    await userEvent.type(title, "夜探听雨楼");
    expect(start).toBeDisabled();          // 只填了战役名
    await userEvent.type(playerName, "沈青");
    expect(start).toBeEnabled();
  });

  it("continues an existing campaign using its first player", async () => {
    mocked.campaigns.mockResolvedValue([
      { id: "c9", title: "旧档", module_id: "misty_hollow",
        active_branch_id: "c9@main", created_at: "" },
    ]);
    mocked.campaign.mockResolvedValue({
      id: "c9", title: "旧档", module_id: "misty_hollow", module_title: "迷雾幽谷",
      active_branch_id: "c9@main", scene_id: "square", turn_id: 2, cost_usd: 0.1,
      players: [{ id: "p9", display_name: "张三" }],
      characters: [], clues_revealed: [],
    } as never);
    const onEnter = vi.fn();
    render(<Lobby onEnter={onEnter} />);
    await userEvent.click(await screen.findByText("继续"));
    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith({
        campaignId: "c9", playerId: "p9", title: "旧档",
      }),
    );
    expect(mocked.campaign).toHaveBeenCalledWith("c9", "test-client");
  });
});

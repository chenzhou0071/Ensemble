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
    await userEvent.click(screen.getByText("开始跑团"));
    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith({
        campaignId: "c1", playerId: "p1", title: "迷雾山谷",
      }),
    );
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
  });
});

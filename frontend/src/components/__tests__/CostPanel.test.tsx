import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CostPanel from "../CostPanel";

vi.mock("../../api/rest", () => ({
  api: {
    usage: vi.fn().mockResolvedValue({
      totals: { calls: 2, tokens_in: 180, tokens_out: 90, cost_usd: 0.0005 },
      cap_usd: 1.0,
      recent: [{ turn_id: 1, role: "gm", model: "qwen3.8-flash",
                 tokens_in: 100, tokens_out: 50, cost_usd: 0.0004,
                 created_at: "2026-01-01T00:00:00" }],
    }),
  },
}));

describe("CostPanel", () => {
  it("renders totals against the cap and recent rows", async () => {
    render(<CostPanel campaignId="c1" />);
    expect(await screen.findByText(/\$0\.0005 \/ \$1\.00/)).toBeInTheDocument();
    expect(await screen.findByText(/gm · qwen3.8-flash/)).toBeInTheDocument();
  });
});

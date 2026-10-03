import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NarrationStream from "../NarrationStream";

describe("NarrationStream", () => {
  it("renders gm and npc segments with names", () => {
    render(
      <NarrationStream
        segments={[{ speaker: "gm", text: "雾来了。" },
                   { speaker: "npc:elder", text: "别去磨坊。" }]}
        live={[]}
        npcNames={{ elder: "村长" }}
      />,
    );
    expect(screen.getByText("雾来了。")).toBeInTheDocument();
    expect(screen.getByText("【村长】")).toBeInTheDocument();
    expect(screen.getByText("别去磨坊。")).toBeInTheDocument();
  });

  it("falls back to npc id and marks the last live segment with a cursor", () => {
    render(<NarrationStream segments={[]}
                             live={[{ speaker: "npc:ghost", text: "……" }]} />);
    expect(screen.getByText("【ghost】")).toBeInTheDocument();
    expect(screen.getByText("……").closest("p")).toHaveClass("cursor");
  });
});

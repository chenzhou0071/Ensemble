import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NpcPanel from "../NpcPanel";

describe("NpcPanel", () => {
  it("lists acquainted npcs present in the current scene only", () => {
    render(<NpcPanel sceneNpcs={["elder"]}
                     knownNpcs={["elder", "innkeeper"]}
                     npcNames={{ elder: "陈长老", innkeeper: "何老板" }} />);
    expect(screen.getByText("已结识人物")).toBeInTheDocument();
    expect(screen.getByText("陈长老")).toBeInTheDocument();
    expect(screen.queryByText("何老板")).not.toBeInTheDocument();   // 不在本场景不显示
  });

  it("keeps the panel with an empty notice when nobody is acquainted", () => {
    render(<NpcPanel sceneNpcs={["elder"]} knownNpcs={[]} npcNames={{}} />);
    expect(screen.getByText("已结识人物")).toBeInTheDocument();
    expect(screen.getByText("本场景暂无已结识的人物")).toBeInTheDocument();
  });
});

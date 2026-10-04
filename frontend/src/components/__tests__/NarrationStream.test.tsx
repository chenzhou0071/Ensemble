import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NarrationStream from "../NarrationStream";

function setupScrollableStory(container: HTMLElement, scrollHeight = 500) {
  const story = container.querySelector(".room-story") as HTMLElement;
  let scrollTop = 0;
  Object.defineProperty(story, "scrollTop", {
    get: () => scrollTop,
    set: (v: number) => { scrollTop = v; },
    configurable: true,
  });
  Object.defineProperty(story, "scrollHeight", { value: scrollHeight, configurable: true });
  Object.defineProperty(story, "clientHeight", { value: 100, configurable: true });
  return story;
}

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

  it("auto-scrolls to bottom as narration arrives", () => {
    const { container, rerender } = render(
      <NarrationStream segments={[{ speaker: "gm", text: "一。" }]} live={[]} />,
    );
    const story = setupScrollableStory(container);
    rerender(
      <NarrationStream segments={[{ speaker: "gm", text: "一。" },
                                  { speaker: "gm", text: "二。" }]} live={[]} />,
    );
    expect(story.scrollTop).toBe(500);
  });

  it("stops auto-scrolling after the user scrolls up", () => {
    const { container, rerender } = render(
      <NarrationStream segments={[{ speaker: "gm", text: "一。" }]} live={[]} />,
    );
    const story = setupScrollableStory(container);
    story.scrollTop = 0;
    fireEvent.scroll(story);
    rerender(
      <NarrationStream segments={[{ speaker: "gm", text: "一。" },
                                  { speaker: "gm", text: "二。" }]} live={[]} />,
    );
    expect(story.scrollTop).toBe(0);
  });
});

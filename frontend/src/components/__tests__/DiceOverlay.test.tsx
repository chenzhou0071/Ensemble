import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DiceOverlay from "../DiceOverlay";

const DICE = { actor: "pc_p1", skill: "侦查", skill_value: 50,
               difficulty: "regular", roll: 12, level: "hard",
               seed: 1, success: true };

afterEach(() => vi.useRealTimers());

describe("DiceOverlay", () => {
  it("does not render without a dice", () => {
    const { container } = render(<DiceOverlay dice={null} onDone={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("scrambles then settles on the final roll and calls onDone", () => {
    vi.useFakeTimers();
    const onDone = vi.fn();
    render(<DiceOverlay dice={DICE} onDone={onDone} />);
    expect(screen.getByText(/侦查（50）/)).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(2000); });
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("困难成功")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(700); });
    expect(onDone).toHaveBeenCalled();
  });

  it("hides verdict and result color while scrambling", () => {
    vi.useFakeTimers();
    render(<DiceOverlay dice={DICE} onDone={() => {}} />);
    act(() => { vi.advanceTimersByTime(300); });
    expect(screen.queryByText("困难成功")).not.toBeInTheDocument();  // 跳动中不揭晓等级
    expect(screen.getByText("……")).toBeInTheDocument();              // 占位符
    expect(document.querySelector(".dice-roll")?.className).not.toMatch(/ok|bad/);
  });

  it("reveals verdict and result color once the roll settles", () => {
    vi.useFakeTimers();
    render(<DiceOverlay dice={DICE} onDone={() => {}} />);
    act(() => { vi.advanceTimersByTime(1300); });
    expect(screen.getByText("困难成功")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(document.querySelector(".dice-roll")?.className).toMatch(/\bok\b/);
  });
});

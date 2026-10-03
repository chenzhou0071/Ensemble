import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import EndingOverlay from "../EndingOverlay";

describe("EndingOverlay", () => {
  it("renders nothing without ending", () => {
    const { container } = render(
      <EndingOverlay endingReached={null} condition={undefined}
                     onLeave={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the ending condition and leave button", async () => {
    const onLeave = vi.fn();
    render(<EndingOverlay endingReached="ending_break" condition="你找到了真相"
                          onLeave={onLeave} />);
    expect(screen.getByText("你找到了真相")).toBeInTheDocument();
    await userEvent.click(screen.getByText("回到大厅"));
    expect(onLeave).toHaveBeenCalled();
  });
});

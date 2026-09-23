import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DeleteMappingModal from "./DeleteMappingModal";

describe("DeleteMappingModal", () => {
  it("shows the container name and confirms deletion when clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onHide = vi.fn();

    render(
      <DeleteMappingModal
        show
        containerName="web-app"
        onHide={onHide}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByText("web-app")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /delete mapping/i }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("cancels without confirming when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onHide = vi.fn();

    render(
      <DeleteMappingModal
        show
        containerName="web-app"
        onHide={onHide}
        onConfirm={onConfirm}
      />,
    );

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onHide).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("renders nothing visible when show is false", () => {
    render(
      <DeleteMappingModal
        show={false}
        containerName="web-app"
        onHide={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.queryByText("Delete Mapping?")).not.toBeInTheDocument();
  });
});

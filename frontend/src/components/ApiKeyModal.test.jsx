import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ApiKeyModal from "./ApiKeyModal";

const setup = (props = {}) => {
  const handlers = {
    onSubmit: vi.fn(),
    onClear: vi.fn(),
    onCancel: vi.fn(),
  };
  render(<ApiKeyModal show {...handlers} {...props} />);
  return handlers;
};

describe("ApiKeyModal", () => {
  it("submits the trimmed key", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();

    await user.type(screen.getByLabelText("API key"), "  secret  ");
    await user.click(screen.getByRole("button", { name: "Save key" }));

    expect(onSubmit).toHaveBeenCalledWith("secret");
  });

  it("disables saving an empty key", () => {
    setup();

    expect(screen.getByRole("button", { name: "Save key" })).toBeDisabled();
  });

  it("explains a rejected key", () => {
    setup({ rejected: true });

    expect(screen.getByRole("alert")).toHaveTextContent(/rejected/i);
  });

  it("offers to clear only when a key is stored", async () => {
    const user = userEvent.setup();
    const { onClear } = setup({ hasKey: true });

    await user.click(screen.getByRole("button", { name: "Clear stored key" }));

    expect(onClear).toHaveBeenCalled();
  });

  it("hides the clear button when no key is stored", () => {
    setup({ hasKey: false });

    expect(
      screen.queryByRole("button", { name: "Clear stored key" }),
    ).not.toBeInTheDocument();
  });

  it("cancels", async () => {
    const user = userEvent.setup();
    const { onCancel } = setup();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalled();
  });
});

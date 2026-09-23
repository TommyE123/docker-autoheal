import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConfigImportExport from "./ConfigImportExport";

describe("ConfigImportExport", () => {
  it("calls onExport when the export button is clicked", async () => {
    const user = userEvent.setup();
    const onExport = vi.fn();

    render(<ConfigImportExport onExport={onExport} onImport={vi.fn()} />);

    await user.click(
      screen.getByRole("button", { name: /export configuration/i }),
    );

    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it("calls onImport with the selected file", async () => {
    const user = userEvent.setup();
    const onImport = vi.fn();
    const { container } = render(
      <ConfigImportExport onExport={vi.fn()} onImport={onImport} />,
    );

    const file = new File(['{"a":1}'], "config.json", {
      type: "application/json",
    });
    const input = container.querySelector("#importFile");

    await user.upload(input, file);

    expect(onImport).toHaveBeenCalledTimes(1);
    expect(input.files[0]).toBe(file);
  });
});

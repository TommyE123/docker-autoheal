import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useTheme } from "./useTheme";

const html = document.documentElement;

describe("useTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    html.removeAttribute("data-bs-theme");
  });
  afterEach(() => localStorage.clear());

  it("defaults to light when nothing is saved", () => {
    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("light");
    expect(html).toHaveAttribute("data-bs-theme", "light");
  });

  it("toggles between light and dark and saves the choice", () => {
    const { result } = renderHook(() => useTheme());

    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe("dark");
    expect(html).toHaveAttribute("data-bs-theme", "dark");
    expect(localStorage.getItem("theme")).toBe("dark");

    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe("light");
    expect(html).toHaveAttribute("data-bs-theme", "light");
    expect(localStorage.getItem("theme")).toBe("light");
  });

  it("restores a saved dark preference", () => {
    localStorage.setItem("theme", "dark");

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("dark");
    expect(html).toHaveAttribute("data-bs-theme", "dark");
  });

  it("ignores an unrecognised saved value", () => {
    localStorage.setItem("theme", "purple");

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("light");
  });
});

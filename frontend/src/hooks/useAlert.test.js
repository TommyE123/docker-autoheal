import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAlert } from "./useAlert";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useAlert", () => {
  it("shows an alert with the given variant and message", () => {
    const { result } = renderHook(() => useAlert());

    act(() => {
      result.current.showAlert("danger", "Something went wrong");
    });

    expect(result.current.alert).toEqual({
      variant: "danger",
      message: "Something went wrong",
    });
  });

  it("auto-dismisses success alerts after 7 seconds", () => {
    const { result } = renderHook(() => useAlert());

    act(() => {
      result.current.showAlert("success", "Saved");
    });
    expect(result.current.alert).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(6999);
    });
    expect(result.current.alert).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(2);
    });
    expect(result.current.alert).toBeNull();
  });

  it("auto-dismisses non-success alerts after 5 seconds", () => {
    const { result } = renderHook(() => useAlert());

    act(() => {
      result.current.showAlert("danger", "Failed");
    });

    act(() => {
      vi.advanceTimersByTime(5001);
    });
    expect(result.current.alert).toBeNull();
  });

  it("clearAlert immediately clears the alert and cancels the pending timeout", () => {
    const { result } = renderHook(() => useAlert());

    act(() => {
      result.current.showAlert("success", "Saved");
    });
    act(() => {
      result.current.clearAlert();
    });

    expect(result.current.alert).toBeNull();
  });
});

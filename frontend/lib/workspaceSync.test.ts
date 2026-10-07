import { afterEach, describe, expect, it, vi } from "vitest";
import { startWorkspaceSync } from "./workspaceSync";

afterEach(() => vi.useRealTimers());

describe("workspace background synchronization", () => {
  it("recovers after a hanging request and ignores its late completion", async () => {
    vi.useFakeTimers();
    let finishOld!: () => void;
    const signals: AbortSignal[] = [];
    const refresh = vi.fn((signal: AbortSignal) => {
      signals.push(signal);
      return signals.length === 1 ? new Promise<void>((resolve) => { finishOld = resolve; }) : Promise.resolve();
    });
    const onError = vi.fn();
    const loop = startWorkspaceSync({ refresh, onError, isVisible: () => true });
    await vi.advanceTimersByTimeAsync(12000);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(signals[0].aborted).toBe(true);
    expect(onError).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(refresh).toHaveBeenCalledTimes(2);
    finishOld();
    await vi.advanceTimersByTimeAsync(5000);
    expect(refresh).toHaveBeenCalledTimes(3);
    loop.stop();
  });

  it("skips hidden pages and resumes immediately when requested", async () => {
    vi.useFakeTimers();
    let visible = false;
    const refresh = vi.fn().mockResolvedValue(undefined);
    const loop = startWorkspaceSync({ refresh, onError: vi.fn(), isVisible: () => visible });
    await vi.advanceTimersByTimeAsync(15000);
    expect(refresh).not.toHaveBeenCalled();
    visible = true;
    loop.sync();
    loop.sync();
    await vi.advanceTimersByTimeAsync(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    loop.stop();
  });

  it("retries failed requests and aborts active requests on logout", async () => {
    vi.useFakeTimers();
    let signal!: AbortSignal;
    const refresh = vi.fn().mockRejectedValueOnce(new Error("offline")).mockImplementation((s: AbortSignal) => {
      signal = s;
      return new Promise<void>(() => {});
    });
    const onError = vi.fn();
    const loop = startWorkspaceSync({ refresh, onError, isVisible: () => true });
    await vi.advanceTimersByTimeAsync(5000);
    expect(refresh).toHaveBeenCalledTimes(2);
    expect(onError).toHaveBeenCalledTimes(1);
    loop.stop();
    expect(signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(60000);
    expect(refresh).toHaveBeenCalledTimes(2);
    expect(onError).toHaveBeenCalledTimes(1);
  });
});

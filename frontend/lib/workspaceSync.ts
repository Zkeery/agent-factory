/** A stalled request must never stop later workspace updates. */
export function startWorkspaceSync({ refresh, isVisible, onError, intervalMs = 5000, timeoutMs = 12000 }: {
  refresh: (signal: AbortSignal) => Promise<void>;
  isVisible: () => boolean;
  onError: () => void;
  intervalMs?: number;
  timeoutMs?: number;
}) {
  let stopped = false;
  let active: AbortController | null = null;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const sync = () => {
    if (stopped || active || !isVisible()) return;
    const controller = new AbortController();
    active = controller;
    timeout = setTimeout(() => {
      if (active !== controller) return;
      controller.abort();
      active = null;
      onError();
    }, timeoutMs);
    void Promise.resolve().then(() => refresh(controller.signal)).catch(() => {
      if (!stopped && active === controller) onError();
    }).finally(() => {
      if (active !== controller) return;
      clearTimeout(timeout);
      active = null;
    });
  };
  const timer = setInterval(sync, intervalMs);
  sync();
  return {
    sync,
    stop() {
      stopped = true;
      clearInterval(timer);
      clearTimeout(timeout);
      active?.abort();
      active = null;
    },
  };
}

import { afterEach, describe, expect, it, vi } from "vitest";

import { connectWorkflowEvents } from "./event-source";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly listeners = new Map<string, Array<(event: MessageEvent) => void>>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener as (event: MessageEvent) => void);
    this.listeners.set(type, listeners);
  }

  emit(type: string, sequence: number) {
    const event = { lastEventId: String(sequence), data: "{}" } as MessageEvent;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  close() {
    this.closed = true;
  }
}

describe("workflow EventSource adapter", () => {
  afterEach(() => {
    FakeEventSource.instances = [];
    vi.useRealTimers();
  });

  it("invalidates only after a persisted sequence advance", () => {
    const onSequence = vi.fn();
    const onStatus = vi.fn();
    const connection = connectWorkflowEvents({
      runId: "11111111-1111-4111-8111-111111111111",
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource,
      onSequence,
      onStatus,
    });
    const source = FakeEventSource.instances[0];

    expect(source.url).toBe(
      "/api/v1/workflow-runs/11111111-1111-4111-8111-111111111111/events",
    );
    expect(source.url).not.toContain("token");
    source.onopen?.();
    source.emit("proposal.validating", 4);
    source.emit("proposal.ready", 4);
    source.emit("proposal.ready", 5);
    source.emit("workflow.waiting_for_decision", 6);

    expect(onStatus).toHaveBeenCalledWith("connected");
    expect(onSequence.mock.calls.map(([sequence]) => sequence)).toEqual([4, 5, 6]);
    connection.close();
    expect(source.closed).toBe(true);
  });

  it("reports reconnecting and polls REST until native EventSource recovers", () => {
    vi.useFakeTimers();
    const onPoll = vi.fn();
    const onStatus = vi.fn();
    const connection = connectWorkflowEvents({
      runId: "11111111-1111-4111-8111-111111111111",
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource,
      onSequence: vi.fn(),
      onStatus,
      onPoll,
      pollIntervalMs: 1000,
    });
    const source = FakeEventSource.instances[0];

    source.onerror?.();
    vi.advanceTimersByTime(2000);
    expect(onStatus).toHaveBeenCalledWith("reconnecting");
    expect(onPoll).toHaveBeenCalledTimes(2);

    source.onopen?.();
    vi.advanceTimersByTime(1000);
    expect(onPoll).toHaveBeenCalledTimes(2);
    connection.close();
  });
});

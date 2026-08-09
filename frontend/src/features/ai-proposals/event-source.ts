export type WorkflowConnectionStatus = "connecting" | "connected" | "reconnecting";

const workflowEventTypes = [
  "workflow.started",
  "workflow.progress",
  "workflow.understanding",
  "workflow.policy_checked",
  "workflow.context_loaded",
  "workflow.needs_input",
  "workflow.generating",
  "workflow.schema_validating",
  "workflow.verifying",
  "workflow.persisting_proposal",
  "workflow.waiting_for_decision",
  "workflow.decision_received",
  "workflow.manual_fallback",
  "workflow.failed",
  "workflow.completed",
  "proposal.created",
  "proposal.validating",
  "proposal.ready",
  "proposal.validation_failed",
] as const;

type ConnectOptions = {
  runId: string;
  onSequence: (sequence: number) => void;
  onStatus: (status: WorkflowConnectionStatus) => void;
  onPoll?: () => void;
  pollIntervalMs?: number;
  eventSourceFactory?: (url: string) => EventSource;
};

export function connectWorkflowEvents({
  runId,
  onSequence,
  onStatus,
  onPoll,
  pollIntervalMs = 5000,
  eventSourceFactory = (url) => new EventSource(url),
}: ConnectOptions) {
  let latestSequence = 0;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  const source = eventSourceFactory(`/api/v1/workflow-runs/${runId}/events`);
  onStatus("connecting");

  function stopPolling() {
    if (pollTimer !== null) clearInterval(pollTimer);
    pollTimer = null;
  }

  function receive(event: MessageEvent) {
    const sequence = Number(event.lastEventId);
    if (!Number.isSafeInteger(sequence) || sequence <= latestSequence) return;
    latestSequence = sequence;
    onSequence(sequence);
  }

  for (const type of workflowEventTypes) source.addEventListener(type, receive);
  source.onopen = () => {
    stopPolling();
    onStatus("connected");
  };
  source.onerror = () => {
    onStatus("reconnecting");
    if (onPoll && pollTimer === null) pollTimer = setInterval(onPoll, pollIntervalMs);
  };

  return {
    close() {
      stopPolling();
      source.close();
    },
  };
}

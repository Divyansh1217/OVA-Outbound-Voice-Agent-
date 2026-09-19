import type { StreamEvent } from "../types";

/**
 * Subscribes to the live SSE stream for a call. Returns an unsubscribe function.
 * Fire-and-forget: malformed frames are ignored.
 */
export function subscribeToCall(
  callId: string,
  onEvent: (event: StreamEvent) => void
): () => void {
  const source = new EventSource(`/api/v1/calls/${callId}/events`);
  source.onmessage = (msg: MessageEvent) => {
    try {
      onEvent(JSON.parse(msg.data) as StreamEvent);
    } catch {
      /* ignore malformed frames (e.g. ping heartbeats) */
    }
  };
  return () => source.close();
}
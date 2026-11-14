import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { PipelineStats } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";

export type SocketState = "connecting" | "connected" | "lost";

/**
 * Live pipeline status over /api/pipeline/ws, written into the shared status
 * query, with automatic reconnect. A connection that hasn't opened yet is
 * "connecting" (not an error state); "lost" only after a previously-open
 * connection drops. REST polling keeps the data fresh either way.
 */
export function usePipelineSocket(onMessage?: (data: PipelineStats) => void): SocketState {
  const queryClient = useQueryClient();
  const [state, setState] = useState<SocketState>("connecting");
  // Latest callback, read per message, so a new one doesn't force a reconnect.
  const onMessageRef = useRef(onMessage);
  useEffect(() => {
    onMessageRef.current = onMessage;
  });

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retryTimer: number | undefined;
    let everConnected = false;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${protocol}//${window.location.host}/api/pipeline/ws`);
      ws.onopen = () => {
        everConnected = true;
        setState("connected");
      };
      ws.onclose = () => {
        if (disposed) return;
        setState(everConnected ? "lost" : "connecting");
        retryTimer = window.setTimeout(connect, 3000);
      };
      ws.onmessage = (event) => {
        try {
          const data: PipelineStats = JSON.parse(event.data);
          queryClient.setQueryData(queryKeys.pipelineStatus, data);
          onMessageRef.current?.(data);
        } catch {
          // A malformed frame; the next one or the poll will catch up.
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      ws?.close();
    };
  }, [queryClient]);

  return state;
}

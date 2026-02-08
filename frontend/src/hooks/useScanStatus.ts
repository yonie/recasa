import { useEffect, useRef } from "react";
import { useStore } from "../store/useStore";
import type { ScanStatus } from "../api/client";

/**
 * WebSocket hook that connects to the scan progress endpoint
 * and updates the store with real-time scan status.
 */
export function useScanStatus() {
  const setScanStatus = useStore((s) => s.setScanStatus);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/api/scan/ws`);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (!data.heartbeat) {
            setScanStatus(data as ScanStatus);
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        // Reconnect after 5 seconds
        setTimeout(connect, 5000);
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    }

    connect();

    return () => {
      wsRef.current?.close();
    };
  }, [setScanStatus]);
}

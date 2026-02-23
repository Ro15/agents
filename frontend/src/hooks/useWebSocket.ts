import { useEffect, useRef, useState } from "react";

export interface WsMessage {
  type: string;
  [key: string]: unknown;
}

export function useWebSocket(url: string) {
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WsMessage;
          setLastMessage(data);
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        // Reconnect after 3 seconds if the connection drops
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [url]);

  return { lastMessage };
}

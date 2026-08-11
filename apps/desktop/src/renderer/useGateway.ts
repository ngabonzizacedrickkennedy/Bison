import { useCallback, useEffect, useRef, useState } from "react";
import { GatewayConnection, type ConnectionState, type LiveEvent } from "./gateway";

export interface GatewayView {
  state: ConnectionState;
  events: LiveEvent[];
  send: (content: string) => boolean;
}

export function useGateway(url: string): GatewayView {
  const connectionRef = useRef<GatewayConnection | null>(null);
  const [state, setState] = useState<ConnectionState>("connecting");
  const [events, setEvents] = useState<LiveEvent[]>([]);

  useEffect(() => {
    const connection = new GatewayConnection(url, {
      onEvent: (event) => {
        setEvents((current) => [...current, event]);
      },
      onStateChange: setState,
    });

    connectionRef.current = connection;
    connection.connect();

    return () => {
      connectionRef.current = null;
      connection.dispose();
    };
  }, [url]);

  const send = useCallback((content: string) => {
    return connectionRef.current?.send(content) ?? false;
  }, []);

  return { state, events, send };
}

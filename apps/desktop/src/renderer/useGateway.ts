import { useCallback, useEffect, useRef, useState } from "react";
import { IDLE, readAnswered, readFailure, readInvoking, type Activity } from "./activity";
import { GatewayConnection, type ConnectionState, type LiveEvent } from "./gateway";
import { fetchHistory, isStoredMessage, type StoredMessage } from "./messages";

export type HistoryState = "loading" | "ready" | "failed";

export interface GatewayView {
  state: ConnectionState;
  historyState: HistoryState;
  messages: StoredMessage[];
  activity: Activity;
  send: (content: string) => boolean;
}

export function useGateway(webSocketUrl: string, httpUrl: string): GatewayView {
  const connectionRef = useRef<GatewayConnection | null>(null);
  const [state, setState] = useState<ConnectionState>("connecting");
  const [historyState, setHistoryState] = useState<HistoryState>("loading");
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [activity, setActivity] = useState<Activity>(IDLE);

  const appendMessage = useCallback((message: StoredMessage) => {
    setMessages((current) => {
      if (current.some((existing) => existing.id === message.id)) {
        return current;
      }
      return [...current, message];
    });
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetchHistory(httpUrl)
      .then((history) => {
        if (cancelled) {
          return;
        }
        setMessages(history);
        setHistoryState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setHistoryState("failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [httpUrl]);

  const handleEvent = useCallback(
    (event: LiveEvent) => {
      if (event.type === "message.persisted" && isStoredMessage(event.payload)) {
        appendMessage(event.payload);
        return;
      }

      if (event.type === "model.invoking") {
        const next = readInvoking(event.payload);
        if (next !== null) {
          setActivity(next);
        }
        return;
      }

      if (event.type === "model.responded") {
        const next = readAnswered(event.payload);
        if (next !== null) {
          setActivity(next);
        }
        return;
      }

      if (event.type === "request.failed") {
        setActivity(readFailure(event.payload));
      }
    },
    [appendMessage],
  );

  useEffect(() => {
    const connection = new GatewayConnection(webSocketUrl, {
      onEvent: handleEvent,
      onStateChange: setState,
    });

    connectionRef.current = connection;
    connection.connect();

    return () => {
      connectionRef.current = null;
      connection.dispose();
    };
  }, [webSocketUrl, handleEvent]);

  const send = useCallback((content: string) => {
    return connectionRef.current?.send(content) ?? false;
  }, []);

  return { state, historyState, messages, activity, send };
}

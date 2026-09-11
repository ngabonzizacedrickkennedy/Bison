import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { IDLE, readAnswered, readFailure, readInvoking, type Activity } from "./activity";
import { GatewayConnection, type ConnectionState, type LiveEvent } from "./gateway";
import {
  fetchHaltState,
  isHaltSignal,
  isResumeReport,
  requestResume,
  requestStop,
  type HaltSignal,
  type HaltStateReport,
} from "./halt";
import { fetchHistory, isStoredMessage, type StoredMessage } from "./messages";

export type HistoryState = "loading" | "ready" | "failed";

export interface HaltView {
  halted: boolean;
  report: HaltStateReport | null;
  signal: HaltSignal | null;
  pending: boolean;
  error: string | null;
  stop: () => void;
  resume: () => void;
  refresh: () => void;
}

export interface GatewayView {
  state: ConnectionState;
  historyState: HistoryState;
  messages: StoredMessage[];
  activity: Activity;
  halt: HaltView;
  send: (content: string) => boolean;
}

interface HaltState {
  report: HaltStateReport | null;
  signal: HaltSignal | null;
  pending: boolean;
  error: string | null;
}

type HaltAction =
  | { kind: "pending" }
  | { kind: "read"; report: HaltStateReport }
  | { kind: "failed"; message: string }
  | { kind: "signalled"; signal: HaltSignal }
  | { kind: "resumed" };

const HALT_IDLE: HaltState = { report: null, signal: null, pending: false, error: null };

const describe = (error: unknown): string => {
  return error instanceof Error ? error.message : String(error);
};

function reduceHalt(state: HaltState, action: HaltAction): HaltState {
  switch (action.kind) {
    case "pending":
      return { ...state, pending: true, error: null };
    case "read":
      return {
        report: action.report,
        signal: action.report.halted ? state.signal : null,
        pending: false,
        error: null,
      };
    case "failed":
      return { ...state, pending: false, error: action.message };
    case "signalled":
      return { ...state, signal: action.signal, error: null };
    case "resumed":
      return { ...state, signal: null, error: null };
  }
}

export function useGateway(webSocketUrl: string, httpUrl: string): GatewayView {
  const connectionRef = useRef<GatewayConnection | null>(null);
  const [state, setState] = useState<ConnectionState>("connecting");
  const [historyState, setHistoryState] = useState<HistoryState>("loading");
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [activity, setActivity] = useState<Activity>(IDLE);
  const [halt, dispatchHalt] = useReducer(reduceHalt, HALT_IDLE);

  const appendMessage = useCallback((message: StoredMessage) => {
    setMessages((current) => {
      if (current.some((existing) => existing.id === message.id)) {
        return current;
      }
      return [...current, message];
    });
  }, []);

  const readHalt = useCallback(async (): Promise<void> => {
    dispatchHalt({ kind: "pending" });

    try {
      dispatchHalt({ kind: "read", report: await fetchHaltState(httpUrl) });
    } catch (error) {
      dispatchHalt({ kind: "failed", message: describe(error) });
    }
  }, [httpUrl]);

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

  useEffect(() => {
    void readHalt();
  }, [readHalt]);

  const handleEvent = useCallback(
    (event: LiveEvent) => {
      if (event.type === "message.persisted" && isStoredMessage(event.payload)) {
        appendMessage(event.payload);
        return;
      }

      if (event.type === "halt") {
        if (isHaltSignal(event.payload)) {
          dispatchHalt({ kind: "signalled", signal: event.payload });
        }
        void readHalt();
        return;
      }

      if (event.type === "halt_resumed") {
        if (isResumeReport(event.payload)) {
          dispatchHalt({ kind: "resumed" });
        }
        void readHalt();
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
    [appendMessage, readHalt],
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

  const stop = useCallback(() => {
    dispatchHalt({ kind: "pending" });

    requestStop(httpUrl)
      .then((signal) => {
        dispatchHalt({ kind: "signalled", signal });
        return readHalt();
      })
      .catch((error: unknown) => {
        dispatchHalt({ kind: "failed", message: describe(error) });
      });
  }, [httpUrl, readHalt]);

  const resume = useCallback(() => {
    dispatchHalt({ kind: "pending" });

    requestResume(httpUrl)
      .then(() => {
        dispatchHalt({ kind: "resumed" });
        return readHalt();
      })
      .catch((error: unknown) => {
        dispatchHalt({ kind: "failed", message: describe(error) });
      });
  }, [httpUrl, readHalt]);

  const refresh = useCallback(() => {
    void readHalt();
  }, [readHalt]);

  return {
    state,
    historyState,
    messages,
    activity,
    halt: {
      halted: halt.signal !== null || (halt.report?.halted ?? false),
      report: halt.report,
      signal: halt.signal,
      pending: halt.pending,
      error: halt.error,
      stop,
      resume,
      refresh,
    },
    send,
  };
}

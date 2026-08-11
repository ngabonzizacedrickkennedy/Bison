export type ConnectionState = "connecting" | "open" | "closed";

export interface LiveEvent {
  type: string;
  request_id: string;
  sequence: number;
  payload?: unknown;
}

export interface GatewayHandlers {
  onEvent: (event: LiveEvent) => void;
  onStateChange: (state: ConnectionState) => void;
}

const isLiveEvent = (value: unknown): value is LiveEvent => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate["type"] === "string" &&
    typeof candidate["request_id"] === "string" &&
    typeof candidate["sequence"] === "number"
  );
};

export class GatewayConnection {
  private socket: WebSocket | null = null;
  private reconnectDelay = 500;
  private reconnectTimer: number | null = null;
  private disposed = false;

  constructor(
    private readonly url: string,
    private readonly handlers: GatewayHandlers,
  ) {}

  connect(): void {
    if (this.disposed) {
      return;
    }

    this.handlers.onStateChange("connecting");
    const socket = new WebSocket(this.url);
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.reconnectDelay = 500;
      this.handlers.onStateChange("open");
    });

    socket.addEventListener("message", (message) => {
      if (typeof message.data !== "string") {
        return;
      }
      try {
        const parsed: unknown = JSON.parse(message.data);
        if (isLiveEvent(parsed)) {
          this.handlers.onEvent(parsed);
        }
      } catch {
        return;
      }
    });

    socket.addEventListener("close", () => {
      this.socket = null;
      this.handlers.onStateChange("closed");
      this.scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      socket.close();
    });
  }

  send(content: string): boolean {
    if (this.socket === null || this.socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.socket.send(JSON.stringify({ type: "message.send", content }));
    return true;
  }

  dispose(): void {
    this.disposed = true;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.reconnectTimer !== null) {
      return;
    }
    const delay = this.reconnectDelay;
    this.reconnectDelay = Math.min(delay * 2, 10000);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}

import { randomUUID } from "node:crypto";
import websocket from "@fastify/websocket";
import Fastify from "fastify";
import { bootstrapHealthy, fetchManifest } from "./bootstrap-client.js";
import { config } from "./config.js";
import { listMessages, persistMessage, taskStoreHealthy } from "./task-store-client.js";

export const SERVICE_NAME = "gateway-service";

interface IncomingMessage {
  type: "message.send";
  content: string;
}

interface OutgoingEvent {
  type: string;
  request_id: string;
  sequence: number;
  payload: unknown;
}

function parseIncoming(raw: string): IncomingMessage {
  const parsed: unknown = JSON.parse(raw);

  if (
    typeof parsed !== "object" ||
    parsed === null ||
    (parsed as { type?: unknown }).type !== "message.send" ||
    typeof (parsed as { content?: unknown }).content !== "string" ||
    (parsed as { content: string }).content.trim() === ""
  ) {
    throw new Error("expected { type: 'message.send', content: <non-empty string> }");
  }

  return parsed as IncomingMessage;
}

export function buildServer() {
  const app = Fastify({ logger: { level: "info" } });

  app.register(websocket);

  app.get("/health", async () => ({
    service: SERVICE_NAME,
    status: "ok",
    task_store: (await taskStoreHealthy()) ? "ok" : "unreachable",
    bootstrap: (await bootstrapHealthy()) ? "ok" : "unreachable",
  }));

  app.get("/messages", async () => listMessages());

  app.get("/manifest", async (_request, reply) => {
    try {
      return await fetchManifest();
    } catch (error) {
      app.log.error({ err: error }, "manifest unavailable");
      return reply.status(503).send({ error: "capability manifest unavailable" });
    }
  });

  app.register(async (instance) => {
    instance.get("/ws", { websocket: true }, (socket) => {
      let sequence = 0;

      const emit = (type: string, requestId: string, payload: unknown): void => {
        const event: OutgoingEvent = {
          type,
          request_id: requestId,
          sequence: (sequence += 1),
          payload,
        };
        socket.send(JSON.stringify(event));
      };

      socket.on("message", (raw: Buffer) => {
        const requestId = randomUUID();

        void (async () => {
          try {
            const incoming = parseIncoming(raw.toString("utf8"));

            emit("request.accepted", requestId, { content: incoming.content });

            const stored = await persistMessage({
              requestId,
              role: "user",
              content: incoming.content,
            });

            emit("message.persisted", requestId, stored);
            emit("request.completed", requestId, { message_id: stored.id });
          } catch (error) {
            app.log.error({ err: error, requestId }, "request failed");
            emit("request.failed", requestId, {
              reason: error instanceof Error ? error.message : String(error),
            });
          }
        })();
      });
    });
  });

  return app;
}

async function main(): Promise<void> {
  const app = buildServer();

  try {
    await app.listen({ port: config.port, host: config.host });
  } catch (error) {
    app.log.error(error);
    process.exit(1);
  }
}

void main();

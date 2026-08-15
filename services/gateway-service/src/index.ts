import { randomUUID } from "node:crypto";
import websocket from "@fastify/websocket";
import type { FastifyReply } from "fastify";
import Fastify from "fastify";
import { bootstrapHealthy, fetchManifest } from "./bootstrap-client.js";
import {
  BrokerError,
  bindRole,
  bindingFor,
  brokerHealthy,
  catalogSearch,
  catalogStatus,
  fetchBudget,
  invoke,
  listBindings,
  listModels,
  openPull,
  refreshCatalog,
} from "./broker-client.js";
import { config } from "./config.js";
import { listMessages, persistMessage, taskStoreHealthy } from "./task-store-client.js";

export const SERVICE_NAME = "gateway-service";

const DEFAULT_SEARCH_LIMIT = 20;
const MAX_SEARCH_LIMIT = 200;

const RESPONDING_ROLE = "mediator";

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

function searchLimit(raw: string | undefined): number {
  if (raw === undefined || raw === "") return DEFAULT_SEARCH_LIMIT;

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) return DEFAULT_SEARCH_LIMIT;

  return Math.min(parsed, MAX_SEARCH_LIMIT);
}

function failureReason(error: unknown): { reason: string; detail: unknown } {
  if (error instanceof BrokerError) {
    return { reason: `model-broker responded ${error.status}`, detail: error.detail };
  }

  if (error instanceof Error) {
    return { reason: error.message, detail: null };
  }

  return { reason: String(error), detail: null };
}

export function buildServer() {
  const app = Fastify({ logger: { level: "info" } });

  app.register(websocket);

  const viaBroker = async <T>(
    reply: FastifyReply,
    run: () => Promise<T>,
  ): Promise<T | FastifyReply> => {
    try {
      return await run();
    } catch (error) {
      if (error instanceof BrokerError) {
        app.log.warn({ status: error.status, detail: error.detail }, "model-broker refused");
        return reply.status(error.status).send({ error: error.detail });
      }

      app.log.error({ err: error }, "model-broker unreachable");
      return reply.status(503).send({ error: "model-broker unavailable" });
    }
  };

  app.get("/health", async () => ({
    service: SERVICE_NAME,
    status: "ok",
    task_store: (await taskStoreHealthy()) ? "ok" : "unreachable",
    bootstrap: (await bootstrapHealthy()) ? "ok" : "unreachable",
    model_broker: (await brokerHealthy()) ? "ok" : "unreachable",
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

  app.get("/models", async (_request, reply) => viaBroker(reply, () => listModels()));

  app.get("/budget", async (_request, reply) => viaBroker(reply, () => fetchBudget()));

  app.get("/catalog/status", async (_request, reply) => viaBroker(reply, () => catalogStatus()));

  app.get("/catalog/search", async (request, reply) => {
    const query = request.query as { q?: string; limit?: string };
    return viaBroker(reply, () => catalogSearch(query.q ?? "", searchLimit(query.limit)));
  });

  app.post("/catalog/refresh", async (_request, reply) => viaBroker(reply, () => refreshCatalog()));

  app.get("/projects/:projectId/bindings", async (request, reply) => {
    const params = request.params as { projectId: string };
    return viaBroker(reply, () => listBindings(params.projectId));
  });

  app.put("/projects/:projectId/bindings/:role", async (request, reply) => {
    const params = request.params as { projectId: string; role: string };
    const body = request.body as { model_id?: unknown; engine_id?: unknown } | null;

    if (body === null || typeof body.model_id !== "string" || body.model_id.trim() === "") {
      return reply.status(400).send({ error: "model_id is required" });
    }

    const payload =
      typeof body.engine_id === "string"
        ? { model_id: body.model_id, engine_id: body.engine_id }
        : { model_id: body.model_id };

    return viaBroker(reply, () => bindRole(params.projectId, params.role, payload));
  });

  app.post("/models/pull/*", async (request, reply) => {
    const params = request.params as Record<string, string>;
    const modelId = params["*"] ?? "";

    if (modelId.trim() === "") {
      return reply.status(400).send({ error: "model id is required" });
    }

    try {
      const stream = await openPull(modelId);
      return reply.header("content-type", "application/x-ndjson").send(stream);
    } catch (error) {
      if (error instanceof BrokerError) {
        app.log.warn({ modelId, status: error.status, detail: error.detail }, "pull refused");
        return reply.status(error.status).send({ error: error.detail });
      }

      app.log.error({ err: error, modelId }, "pull failed to start");
      return reply.status(503).send({ error: "model-broker unavailable" });
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

            const asked = await persistMessage({
              requestId,
              role: "user",
              content: incoming.content,
            });

            emit("message.persisted", requestId, asked);

            const binding = await bindingFor(config.projectId, RESPONDING_ROLE);

            if (binding === null) {
              throw new Error(`no ${RESPONDING_ROLE} binding for project ${config.projectId}`);
            }

            emit("model.invoking", requestId, {
              role: binding.role,
              model_id: binding.model_id,
              locality: binding.locality,
            });

            const answer = await invoke({
              requestId,
              modelId: binding.model_id,
              role: binding.role,
              prompt: incoming.content,
              engineId: binding.engine_id,
            });

            emit("model.responded", requestId, {
              model_id: answer.model_id,
              latency_ms: answer.latency_ms,
              failed_over_from: answer.failed_over_from,
            });

            const answered = await persistMessage({
              requestId,
              role: "assistant",
              content: answer.response,
            });

            emit("message.persisted", requestId, answered);
            emit("request.completed", requestId, { message_id: answered.id });
          } catch (error) {
            app.log.error({ err: error, requestId }, "request failed");
            emit("request.failed", requestId, failureReason(error));
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

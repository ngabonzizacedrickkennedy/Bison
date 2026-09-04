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
import { broadcast, isHaltReason } from "./halt.js";
import {
  ProjectError,
  createTask,
  fetchProgress,
  listTasks,
  moveTask,
  projectHealthy,
} from "./project-client.js";
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

  const clients = new Set<(type: string, requestId: string, payload: unknown) => void>();

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

  const viaProject = async <T>(
    reply: FastifyReply,
    run: () => Promise<T>,
  ): Promise<T | FastifyReply> => {
    try {
      return await run();
    } catch (error) {
      if (error instanceof ProjectError) {
        app.log.warn({ status: error.status, detail: error.detail }, "project-service refused");
        return reply.status(error.status).send({ error: error.detail });
      }

      app.log.error({ err: error }, "project-service unreachable");
      return reply.status(503).send({ error: "project-service unavailable" });
    }
  };

  app.get("/health", async () => ({
    service: SERVICE_NAME,
    status: "ok",
    task_store: (await taskStoreHealthy()) ? "ok" : "unreachable",
    bootstrap: (await bootstrapHealthy()) ? "ok" : "unreachable",
    model_broker: (await brokerHealthy()) ? "ok" : "unreachable",
    project_service: (await projectHealthy()) ? "ok" : "unreachable",
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

  app.get("/projects/:projectId/tasks", async (request, reply) => {
    const params = request.params as { projectId: string };
    return viaProject(reply, () => listTasks(params.projectId));
  });

  app.get("/projects/:projectId/progress", async (request, reply) => {
    const params = request.params as { projectId: string };
    return viaProject(reply, () => fetchProgress(params.projectId));
  });

  app.post("/projects/:projectId/tasks", async (request, reply) => {
    const params = request.params as { projectId: string };
    const body = request.body as {
      title?: unknown;
      kind?: unknown;
      description?: unknown;
      parent_id?: unknown;
      depends_on?: unknown;
    } | null;

    if (body === null || typeof body.title !== "string" || body.title.trim() === "") {
      return reply.status(400).send({ error: "title is required" });
    }

    if (typeof body.kind !== "string" || body.kind.trim() === "") {
      return reply.status(400).send({ error: "kind is required" });
    }

    const draft = {
      title: body.title,
      kind: body.kind,
      origin: "user",
      description: typeof body.description === "string" ? body.description : "",
      parent_id: typeof body.parent_id === "string" ? body.parent_id : null,
      depends_on: Array.isArray(body.depends_on)
        ? body.depends_on.filter((entry): entry is string => typeof entry === "string")
        : [],
    };

    reply.status(201);

    return viaProject(reply, () => createTask(params.projectId, draft));
  });

  app.post("/tasks/:taskId/state", async (request, reply) => {
    const params = request.params as { taskId: string };
    const body = request.body as { state?: unknown; reason?: unknown; actor?: unknown } | null;

    if (body === null || typeof body.state !== "string" || body.state.trim() === "") {
      return reply.status(400).send({ error: "state is required" });
    }

    const move = {
      state: body.state,
      reason: typeof body.reason === "string" && body.reason.trim() !== "" ? body.reason : null,
      actor: typeof body.actor === "string" && body.actor.trim() !== "" ? body.actor : "user",
    };

    return viaProject(reply, () => moveTask(params.taskId, move));
  });

  app.post("/halt", async (request, reply) => {
    const body = request.body as {
      reason?: unknown;
      request_id?: unknown;
      project_id?: unknown;
      task_id?: unknown;
    } | null;

    const reason = body?.reason ?? "kill_switch";

    if (!isHaltReason(reason)) {
      return reply.status(422).send({ error: `unknown halt reason "${String(reason)}"` });
    }

    const signal = await broadcast({
      reason,
      requestId: typeof body?.request_id === "string" ? body.request_id : null,
      projectId: typeof body?.project_id === "string" ? body.project_id : null,
      taskId: typeof body?.task_id === "string" ? body.task_id : null,
    });

    app.log.warn(
      {
        halt: signal.id,
        reason: signal.reason,
        acknowledged: signal.acknowledged_count,
        silent: signal.silent_count,
      },
      "HALT broadcast",
    );

    for (const emit of clients) {
      emit("halt", signal.request_id ?? signal.id, signal);
    }

    return signal;
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

      clients.add(emit);

      socket.on("close", () => {
        clients.delete(emit);
      });

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

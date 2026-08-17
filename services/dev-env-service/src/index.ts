import Fastify, { type FastifyInstance } from "fastify";
import { HaltState, parseSignal, type Boundary } from "./halt.js";

export const SERVICE_NAME = "dev-env-service";

const BOUNDARY: Boundary = "between_actions";

function intFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer, received "${raw}"`);
  }

  return parsed;
}

export const config = {
  port: intFromEnv("BISON_DEV_ENV_PORT", 9000),
  host: process.env.BISON_DEV_ENV_HOST ?? "127.0.0.1",
} as const;

export function buildServer(): FastifyInstance {
  const app = Fastify({ logger: true });
  const haltState = new HaltState(SERVICE_NAME, BOUNDARY);

  app.get("/health", async () => ({
    service: SERVICE_NAME,
    status: haltState.halted ? "halted" : "ok",
    boundary: BOUNDARY,
    halted: haltState.halted,
  }));

  app.post("/halt", async (request, reply) => {
    let signal;

    try {
      signal = parseSignal(request.body);
    } catch (error) {
      return reply.status(422).send({ error: (error as Error).message });
    }

    const acknowledgement = haltState.accept(signal);

    app.log.warn({ halt: signal.id, reason: signal.reason, boundary: BOUNDARY }, "HALT accepted");

    return acknowledgement;
  });

  app.get("/halt/state", async () => haltState.status());

  app.post("/halt/resume", async (request, reply) => {
    const actor = (request.body as { actor?: unknown } | null)?.actor;

    if (typeof actor !== "string" || actor.length === 0) {
      return reply.status(422).send({ error: "resume requires a non-empty actor" });
    }

    return haltState.resume(actor);
  });

  return app;
}

async function start(): Promise<void> {
  const app = buildServer();

  try {
    await app.listen({ port: config.port, host: config.host });
  } catch (error) {
    app.log.error(error);
    process.exit(1);
  }
}

if (process.argv[1]?.endsWith("index.js")) {
  await start();
}

import { connect } from "node:net";
import type { CacheBackend } from "@bison/contracts";
import { probeCapability, type Capability } from "../capability.js";
import { config } from "../config.js";

const REDIS_TIMEOUT_MS = 1_500;
const IN_PROCESS_TTL_MS = 25;

async function redisAnswersPing(): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    const socket = connect({ host: config.redisHost, port: config.redisPort });
    let settled = false;

    const finish = (result: boolean): void => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(result);
    };

    socket.setTimeout(REDIS_TIMEOUT_MS);
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));

    socket.once("connect", () => socket.write("PING\r\n"));
    socket.once("data", (chunk: Buffer) => finish(chunk.toString("utf8").startsWith("+PONG")));
  });
}

async function inProcessStoreExpires(): Promise<boolean> {
  const store = new Map<string, { value: string; expiresAt: number }>();
  const key = "bison-capability-probe";

  store.set(key, { value: "present", expiresAt: Date.now() + IN_PROCESS_TTL_MS });

  const read = (): string | undefined => {
    const entry = store.get(key);
    if (entry === undefined) return undefined;

    if (entry.expiresAt <= Date.now()) {
      store.delete(key);
      return undefined;
    }

    return entry.value;
  };

  if (read() !== "present") return false;

  await new Promise((resolve) => setTimeout(resolve, IN_PROCESS_TTL_MS * 2));

  return read() === undefined;
}

export async function probeCache(): Promise<Capability<CacheBackend>> {
  return probeCapability<CacheBackend>([
    { backend: "redis", strength: "full", works: redisAnswersPing },
    { backend: "in_process", strength: "full", works: inProcessStoreExpires },
  ]);
}

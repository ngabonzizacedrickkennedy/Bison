import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import type { SandboxBackend } from "@bison/contracts";
import { probeCapability, type Capability } from "../capability.js";

const run = promisify(execFile);

const DOCKER_TIMEOUT_MS = 90_000;
const PROCESS_TIMEOUT_MS = 15_000;

const WASM_MODULE = new Uint8Array([
  0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00, 0x01, 0x05, 0x01, 0x60, 0x00, 0x01, 0x7f, 0x03,
  0x02, 0x01, 0x00, 0x07, 0x05, 0x01, 0x01, 0x66, 0x00, 0x00, 0x0a, 0x06, 0x01, 0x04, 0x00, 0x41,
  0x2a, 0x0b,
]);

interface WasmRuntime {
  instantiate: (bytes: Uint8Array) => Promise<{ instance: { exports: Record<string, unknown> } }>;
}

function wasmRuntime(): WasmRuntime | undefined {
  return (globalThis as { WebAssembly?: WasmRuntime }).WebAssembly;
}

async function dockerStartsContainer(): Promise<boolean> {
  try {
    const { stdout } = await run("docker", ["run", "--rm", "hello-world"], {
      timeout: DOCKER_TIMEOUT_MS,
    });

    return stdout.includes("Hello from Docker!");
  } catch {
    return false;
  }
}

async function processTreeTerminable(): Promise<boolean> {
  if (process.platform !== "win32") return false;

  const child = spawn("cmd", ["/c", "ping", "-n", "30", "127.0.0.1"], {
    stdio: "ignore",
    windowsHide: true,
  });

  const pid = child.pid;

  if (pid === undefined) {
    child.kill();
    return false;
  }

  const terminated = new Promise<boolean>((resolve) => {
    const timer = setTimeout(() => resolve(false), PROCESS_TIMEOUT_MS);

    child.once("exit", () => {
      clearTimeout(timer);
      resolve(true);
    });

    child.once("error", () => {
      clearTimeout(timer);
      resolve(false);
    });
  });

  try {
    await run("taskkill", ["/PID", String(pid), "/T", "/F"], { timeout: PROCESS_TIMEOUT_MS });
  } catch {
    child.kill();
    return false;
  }

  return terminated;
}

async function wasmModuleRuns(): Promise<boolean> {
  const runtime = wasmRuntime();

  if (runtime === undefined) return false;

  try {
    const { instance } = await runtime.instantiate(WASM_MODULE);
    const exported = instance.exports["f"];

    return typeof exported === "function" && (exported as () => number)() === 42;
  } catch {
    return false;
  }
}

export async function probeSandbox(): Promise<Capability<SandboxBackend>> {
  return probeCapability<SandboxBackend>([
    { backend: "docker", strength: "full", works: dockerStartsContainer },
    { backend: "job_object", strength: "medium", works: processTreeTerminable },
    { backend: "wasm", strength: "weak", works: wasmModuleRuns },
  ]);
}

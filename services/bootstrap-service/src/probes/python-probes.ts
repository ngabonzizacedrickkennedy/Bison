import { execFile } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { config } from "../config.js";

const run = promisify(execFile);

const PROBE_TIMEOUT_MS = 300_000;

export interface PythonProbeResults {
  sqlite: boolean;
  postgres: boolean;
  input_injection_available: boolean;
  input_injection_verified: boolean;
  screen_capture: boolean;
}

const ALL_FAILED: PythonProbeResults = {
  sqlite: false,
  postgres: false,
  input_injection_available: false,
  input_injection_verified: false,
  screen_capture: false,
};

function probeProjectDir(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "probe");
}

function isResults(value: unknown): value is PythonProbeResults {
  if (typeof value !== "object" || value === null) return false;

  const shape = value as Record<string, unknown>;

  return (
    typeof shape["sqlite"] === "boolean" &&
    typeof shape["postgres"] === "boolean" &&
    typeof shape["input_injection_available"] === "boolean" &&
    typeof shape["input_injection_verified"] === "boolean" &&
    typeof shape["screen_capture"] === "boolean"
  );
}

async function execute(): Promise<PythonProbeResults> {
  try {
    const { stdout } = await run(
      "uv",
      ["run", "--project", probeProjectDir(), "python", "-m", "bison_probe"],
      {
        timeout: PROBE_TIMEOUT_MS,
        env: {
          ...process.env,
          BISON_POSTGRES_HOST: config.postgresHost,
          BISON_POSTGRES_PORT: String(config.postgresPort),
        },
      },
    );

    const lastLine = stdout.trim().split(/\r?\n/).pop();

    if (lastLine === undefined || lastLine === "") return ALL_FAILED;

    const parsed: unknown = JSON.parse(lastLine);

    return isResults(parsed) ? parsed : ALL_FAILED;
  } catch {
    return ALL_FAILED;
  }
}

let pending: Promise<PythonProbeResults> | undefined;

export function runPythonProbes(): Promise<PythonProbeResults> {
  pending ??= execute();
  return pending;
}

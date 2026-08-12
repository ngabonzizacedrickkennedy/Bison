import type { DatabaseBackend } from "@bison/contracts";
import { probeCapability, type Capability } from "../capability.js";
import { runPythonProbes } from "./python-probes.js";

export async function probeDatabase(): Promise<Capability<DatabaseBackend>> {
  const results = await runPythonProbes();

  return probeCapability<DatabaseBackend>([
    { backend: "postgres", strength: "full", works: async () => results.postgres },
    { backend: "sqlite", strength: "full", works: async () => results.sqlite },
  ]);
}

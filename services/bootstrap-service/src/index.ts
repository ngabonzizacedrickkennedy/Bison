import type { CapabilityManifest } from "@bison/contracts";
import Fastify from "fastify";
import { config } from "./config.js";
import { MINIMUM_RAM_GB, meetsMinimumRam } from "./hardware.js";
import { buildManifest, degradedCapabilities, manifestPath, writeManifest } from "./manifest.js";

export const SERVICE_NAME = "bootstrap-service";

export function buildServer(manifest: CapabilityManifest) {
  const app = Fastify({ logger: { level: "info" } });

  app.get("/health", async () => ({
    service: SERVICE_NAME,
    status: "ok",
    data_dir: config.dataDir,
    manifest_path: manifestPath(),
    generated_at: manifest.generated_at,
  }));

  app.get("/manifest", async () => manifest);

  return app;
}

async function main(): Promise<void> {
  const manifest = await buildManifest();
  const written = await writeManifest(manifest);
  const app = buildServer(manifest);

  app.log.info({ path: written }, "capability manifest written");

  if (!meetsMinimumRam(manifest.hardware)) {
    app.log.warn(
      { ram_gb: manifest.hardware.ram_gb, minimum_ram_gb: MINIMUM_RAM_GB },
      "machine is below the minimum supported memory",
    );
  }

  const degraded = degradedCapabilities(manifest);

  if (degraded.length > 0) {
    app.log.warn({ degraded }, "running on degraded backends");
  }

  try {
    await app.listen({ port: config.port, host: config.host });
  } catch (error) {
    app.log.error(error);
    process.exit(1);
  }
}

void main();

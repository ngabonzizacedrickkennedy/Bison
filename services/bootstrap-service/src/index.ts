import Fastify from "fastify";
import { config } from "./config.js";
import { MINIMUM_RAM_GB, meetsMinimumRam, probeHardware } from "./hardware.js";
import { probeSandbox } from "./probes/sandbox.js";
import { probeSecrets } from "./probes/secrets.js";

export const SERVICE_NAME = "bootstrap-service";

export function buildServer() {
  const app = Fastify({ logger: { level: "info" } });

  app.get("/health", async () => ({
    service: SERVICE_NAME,
    status: "ok",
    data_dir: config.dataDir,
  }));

  app.get("/hardware", async () => {
    const hardware = await probeHardware();

    return {
      hardware,
      minimum_ram_gb: MINIMUM_RAM_GB,
      meets_minimum_ram: meetsMinimumRam(hardware),
    };
  });

  app.get("/capabilities", async () => {
    const [sandbox, secrets] = await Promise.all([probeSandbox(), probeSecrets()]);

    return { sandbox, secrets };
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

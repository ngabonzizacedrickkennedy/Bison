import { rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { CapabilityManifestSchema, type CapabilityManifest } from "@bison/contracts";
import { deriveBudgets } from "./budgets.js";
import { config } from "./config.js";
import { probeHardware } from "./hardware.js";
import { probeCache } from "./probes/cache.js";
import { probeDatabase } from "./probes/database.js";
import { probeInputInjection } from "./probes/input-injection.js";
import { probeOcr } from "./probes/ocr.js";
import { probeSandbox } from "./probes/sandbox.js";
import { probeScreenCapture } from "./probes/screen-capture.js";
import { probeSecrets } from "./probes/secrets.js";

export const MANIFEST_SCHEMA_VERSION = 1;

export function manifestPath(): string {
  return join(config.dataDir, "capabilities.json");
}

export async function buildManifest(): Promise<CapabilityManifest> {
  const [hardware, sandbox, secrets, ocr, database, cache, inputInjection, screenCapture] =
    await Promise.all([
      probeHardware(),
      probeSandbox(),
      probeSecrets(),
      probeOcr(),
      probeDatabase(),
      probeCache(),
      probeInputInjection(),
      probeScreenCapture(),
    ]);

  return CapabilityManifestSchema.parse({
    schema_version: MANIFEST_SCHEMA_VERSION,
    generated_at: new Date().toISOString(),
    sandbox,
    secrets,
    ocr,
    database,
    cache,
    input_injection: inputInjection,
    screen_capture: screenCapture,
    hardware,
    budgets: deriveBudgets(hardware),
  });
}

export async function writeManifest(manifest: CapabilityManifest): Promise<string> {
  const target = manifestPath();
  const temporary = `${target}.${process.pid}.tmp`;

  await writeFile(temporary, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  await rename(temporary, target);

  return target;
}

export function degradedCapabilities(manifest: CapabilityManifest): string[] {
  const entries = [
    ["sandbox", manifest.sandbox],
    ["secrets", manifest.secrets],
    ["ocr", manifest.ocr],
    ["database", manifest.database],
    ["cache", manifest.cache],
    ["input_injection", manifest.input_injection],
    ["screen_capture", manifest.screen_capture],
  ] as const;

  return entries
    .filter(
      ([, capability]) => capability.strength !== "full" && capability.strength !== "verified",
    )
    .map(([name, capability]) => `${name}=${capability.backend ?? "none"}:${capability.strength}`);
}

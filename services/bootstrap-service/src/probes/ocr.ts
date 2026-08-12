import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { OcrBackend } from "@bison/contracts";
import { probeCapability, type Capability } from "../capability.js";
import { config } from "../config.js";

const run = promisify(execFile);

const VERSION_TIMEOUT_MS = 10_000;

async function respondsToVersion(executable: string): Promise<boolean> {
  try {
    const { stdout } = await run(executable, ["--version"], { timeout: VERSION_TIMEOUT_MS });

    return stdout.toLowerCase().includes("tesseract");
  } catch {
    return false;
  }
}

export async function probeOcr(): Promise<Capability<OcrBackend>> {
  return probeCapability<OcrBackend>([
    {
      backend: "tesseract_bundled",
      strength: "full",
      works: () => respondsToVersion(config.tesseractPath),
    },
    {
      backend: "tesseract_system",
      strength: "medium",
      works: () => respondsToVersion("tesseract"),
    },
  ]);
}

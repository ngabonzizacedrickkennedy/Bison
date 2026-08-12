import { join } from "node:path";
import { resolveDataDir } from "./paths.js";

function intFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer, received "${raw}"`);
  }

  return parsed;
}

const dataDir = resolveDataDir();

export const config = {
  port: intFromEnv("BISON_BOOTSTRAP_PORT", 8200),
  host: process.env.BISON_BOOTSTRAP_HOST ?? "127.0.0.1",
  dataDir,
  tesseractPath:
    process.env.BISON_TESSERACT_PATH ?? join(dataDir, "vendor", "tesseract", "tesseract.exe"),
  redisHost: process.env.BISON_REDIS_HOST ?? "127.0.0.1",
  redisPort: intFromEnv("BISON_REDIS_PORT", 6379),
  postgresHost: process.env.BISON_POSTGRES_HOST ?? "127.0.0.1",
  postgresPort: intFromEnv("BISON_POSTGRES_PORT", 5432),
} as const;

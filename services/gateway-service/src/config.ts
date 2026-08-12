function intFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer, received "${raw}"`);
  }

  return parsed;
}

function urlFromEnv(name: string, fallback: string): string {
  const raw = process.env[name];
  const value = raw === undefined || raw === "" ? fallback : raw;

  try {
    new URL(value);
  } catch {
    throw new Error(`${name} must be a valid URL, received "${value}"`);
  }

  return value.replace(/\/$/, "");
}

export const config = {
  port: intFromEnv("BISON_GATEWAY_PORT", 8000),
  host: process.env.BISON_GATEWAY_HOST ?? "127.0.0.1",
  taskStoreUrl: urlFromEnv("BISON_TASK_STORE_URL", "http://127.0.0.1:8100"),
  bootstrapUrl: urlFromEnv("BISON_BOOTSTRAP_URL", "http://127.0.0.1:8200"),
  userId: process.env.BISON_USER_ID ?? "local",
} as const;

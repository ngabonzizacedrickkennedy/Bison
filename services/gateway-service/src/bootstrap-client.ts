import { request } from "undici";
import { config } from "./config.js";

export class BootstrapError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`bootstrap responded ${status}: ${body}`);
    this.name = "BootstrapError";
  }
}

export async function fetchManifest(): Promise<unknown> {
  const response = await request(`${config.bootstrapUrl}/manifest`, { method: "GET" });
  const text = await response.body.text();

  if (response.statusCode >= 400) {
    throw new BootstrapError(response.statusCode, text);
  }

  return JSON.parse(text) as unknown;
}

export async function bootstrapHealthy(): Promise<boolean> {
  try {
    const response = await request(`${config.bootstrapUrl}/health`, { method: "GET" });
    await response.body.text();
    return response.statusCode < 400;
  } catch {
    return false;
  }
}

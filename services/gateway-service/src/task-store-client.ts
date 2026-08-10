import { request } from "undici";
import { config } from "./config.js";

export interface StoredMessage {
  id: string;
  request_id: string;
  user_id: string;
  role: string;
  content: string;
  created_at: string;
}

export class TaskStoreError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`task-store responded ${status}: ${body}`);
    this.name = "TaskStoreError";
  }
}

async function send<T>(method: "GET" | "POST", path: string, payload?: unknown): Promise<T> {
  const options =
    payload === undefined
      ? { method }
      : {
          method,
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        };

  const response = await request(`${config.taskStoreUrl}${path}`, options);

  const text = await response.body.text();

  if (response.statusCode >= 400) {
    throw new TaskStoreError(response.statusCode, text);
  }

  return JSON.parse(text) as T;
}

export async function persistMessage(input: {
  requestId: string;
  role: "user" | "assistant";
  content: string;
}): Promise<StoredMessage> {
  return send<StoredMessage>("POST", "/messages", {
    request_id: input.requestId,
    user_id: config.userId,
    role: input.role,
    content: input.content,
  });
}

export async function listMessages(): Promise<StoredMessage[]> {
  return send<StoredMessage[]>("GET", "/messages");
}

export async function taskStoreHealthy(): Promise<boolean> {
  try {
    await send<unknown>("GET", "/health");
    return true;
  } catch {
    return false;
  }
}

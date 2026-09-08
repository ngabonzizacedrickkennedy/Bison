import { Readable } from "node:stream";
import { request } from "undici";
import { config } from "./config.js";

export interface TreeTask {
  ref: string;
  task_id: string;
  parent_ref: string | null;
  title: string;
  kind: string;
  assigned_role: string;
  depends_on: string[];
  criterion_ids: string[];
}

export interface Decomposition {
  project_id: string;
  request_id: string;
  approach_summary: string;
  engine_model_id: string;
  mediator_model_id: string;
  engine_prompt: string;
  mediator_prompt: string;
  attempts: number;
  repaired: boolean;
  execution_order: string[];
  tasks: TreeTask[];
}

export class MediatorError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`mediator-service responded ${status}`);
    this.name = "MediatorError";
  }
}

function readDetail(text: string): unknown {
  try {
    const parsed: unknown = JSON.parse(text);
    if (typeof parsed === "object" && parsed !== null && "detail" in parsed) {
      return (parsed as { detail: unknown }).detail;
    }
    return parsed;
  } catch {
    return text;
  }
}

function withRequestId(path: string, requestId: string | null): string {
  return requestId === null ? path : `${path}?request_id=${encodeURIComponent(requestId)}`;
}

async function send<T>(method: "GET" | "POST", path: string): Promise<T> {
  const response = await request(`${config.mediatorUrl}${path}`, { method });
  const text = await response.body.text();

  if (response.statusCode >= 400) {
    throw new MediatorError(response.statusCode, readDetail(text));
  }

  return JSON.parse(text) as T;
}

async function openStream(path: string): Promise<Readable> {
  const response = await request(`${config.mediatorUrl}${path}`, {
    method: "POST",
    headersTimeout: 0,
    bodyTimeout: 0,
  });

  if (response.statusCode >= 400) {
    const text = await response.body.text();
    throw new MediatorError(response.statusCode, readDetail(text));
  }

  return response.body;
}

export async function buildTree(
  projectId: string,
  requestId: string | null,
): Promise<Decomposition> {
  return send<Decomposition>(
    "POST",
    withRequestId(`/projects/${encodeURIComponent(projectId)}/tree`, requestId),
  );
}

export async function openRun(projectId: string, requestId: string | null): Promise<Readable> {
  return openStream(withRequestId(`/projects/${encodeURIComponent(projectId)}/run`, requestId));
}

export async function openConfirm(stepId: string, requestId: string | null): Promise<Readable> {
  return openStream(withRequestId(`/steps/${encodeURIComponent(stepId)}/confirm`, requestId));
}

export async function mediatorHealthy(): Promise<boolean> {
  try {
    await send<unknown>("GET", "/health");
    return true;
  } catch {
    return false;
  }
}

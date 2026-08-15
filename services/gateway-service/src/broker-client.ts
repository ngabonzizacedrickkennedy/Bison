import type { Readable } from "node:stream";
import { request } from "undici";
import { config } from "./config.js";

export interface ModelDescriptor {
  model_id: string;
  provider: string;
  locality: string;
  size_gb: number | null;
  context_window: number | null;
  installed: boolean;
}

export interface CatalogEntry {
  model_id: string;
  provider: string;
  locality: string;
  size_gb: number | null;
  capability_tags: string[];
  context_window: number | null;
  indexed_at: string;
}

export interface CatalogStatus {
  entries: number;
  indexed_at: string | null;
  sources: string[];
}

export interface Budget {
  budget_gb: number;
  used_gb: number;
  headroom_gb: number;
}

export interface RoleBinding {
  id: string;
  project_id: string;
  role: string;
  model_id: string;
  engine_id: string | null;
  locality: string;
  prompt_version: string;
  bound_at: string;
}

export interface BindPayload {
  model_id: string;
  engine_id?: string;
}

export class BrokerError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`model-broker responded ${status}`);
    this.name = "BrokerError";
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

async function send<T>(
  method: "GET" | "POST" | "PUT",
  path: string,
  payload?: unknown,
): Promise<T> {
  const options =
    payload === undefined
      ? { method }
      : {
          method,
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        };

  const response = await request(`${config.brokerUrl}${path}`, options);
  const text = await response.body.text();

  if (response.statusCode >= 400) {
    throw new BrokerError(response.statusCode, readDetail(text));
  }

  return JSON.parse(text) as T;
}

export async function listModels(): Promise<ModelDescriptor[]> {
  return send<ModelDescriptor[]>("GET", "/models");
}

export async function fetchBudget(): Promise<Budget> {
  return send<Budget>("GET", "/budget");
}

export async function catalogStatus(): Promise<CatalogStatus> {
  return send<CatalogStatus>("GET", "/catalog/status");
}

export async function catalogSearch(query: string, limit: number): Promise<CatalogEntry[]> {
  const search = new URLSearchParams({ q: query, limit: String(limit) });
  return send<CatalogEntry[]>("GET", `/catalog/search?${search.toString()}`);
}

export async function refreshCatalog(): Promise<CatalogStatus> {
  return send<CatalogStatus>("POST", "/catalog/refresh");
}

export async function listBindings(projectId: string): Promise<RoleBinding[]> {
  return send<RoleBinding[]>("GET", `/projects/${encodeURIComponent(projectId)}/bindings`);
}

export async function bindRole(
  projectId: string,
  role: string,
  payload: BindPayload,
): Promise<RoleBinding> {
  return send<RoleBinding>(
    "PUT",
    `/projects/${encodeURIComponent(projectId)}/bindings/${encodeURIComponent(role)}`,
    payload,
  );
}

export async function openPull(modelId: string): Promise<Readable> {
  const response = await request(`${config.brokerUrl}/models/pull/${modelId}`, { method: "POST" });

  if (response.statusCode >= 400) {
    const text = await response.body.text();
    throw new BrokerError(response.statusCode, readDetail(text));
  }

  return response.body;
}

export async function brokerHealthy(): Promise<boolean> {
  try {
    await send<unknown>("GET", "/health");
    return true;
  } catch {
    return false;
  }
}

export interface InvokeResult {
  request_id: string;
  model_id: string;
  engine_id: string | null;
  response: string;
  failed_over_from: string | null;
  latency_ms: number;
  completed_at: string;
}

export interface InvokeInput {
  requestId: string;
  modelId: string;
  role: string;
  prompt: string;
  engineId: string | null;
}

export async function bindingFor(projectId: string, role: string): Promise<RoleBinding | null> {
  const bindings = await listBindings(projectId);
  return bindings.find((binding) => binding.role === role) ?? null;
}

export async function invoke(input: InvokeInput): Promise<InvokeResult> {
  const payload: Record<string, unknown> = {
    request_id: input.requestId,
    model_id: input.modelId,
    role: input.role,
    prompt: input.prompt,
    mode: "completion",
    timeout_ms: config.invokeTimeoutMs,
  };

  if (input.engineId !== null) {
    payload["engine_id"] = input.engineId;
  }

  return send<InvokeResult>("POST", "/invoke", payload);
}

import { request } from "undici";
import { config } from "./config.js";

export interface Task {
  id: string;
  project_id: string;
  parent_id: string | null;
  title: string;
  description: string;
  origin: string;
  kind: string;
  state: string;
  state_reason: string | null;
  depends_on: string[];
  assigned_role: string;
  position: number;
}

export interface TaskDraft {
  title: string;
  kind: string;
  description?: string;
  origin?: string;
  assigned_role?: string;
  parent_id?: string | null;
  depends_on?: string[];
  position?: number;
}

export interface TaskMove {
  state: string;
  reason?: string | null;
  actor?: string;
}

export interface Progress {
  task_id: string;
  percentage: number;
  verified_weight: number;
  counted_weight: number;
  criteria_total: number;
  criteria_verified: number;
  criteria_failed: number;
  criteria_ignored: number;
}

export interface ProgressSnapshot {
  project_id: string;
  overall: Progress;
  per_task: Progress[];
}

export class ProjectError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`project-service responded ${status}`);
    this.name = "ProjectError";
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

async function send<T>(method: "GET" | "POST", path: string, payload?: unknown): Promise<T> {
  const options =
    payload === undefined
      ? { method }
      : {
          method,
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        };

  const response = await request(`${config.projectUrl}${path}`, options);
  const text = await response.body.text();

  if (response.statusCode >= 400) {
    throw new ProjectError(response.statusCode, readDetail(text));
  }

  return JSON.parse(text) as T;
}

export async function listTasks(projectId: string): Promise<Task[]> {
  return send<Task[]>("GET", `/projects/${encodeURIComponent(projectId)}/tasks`);
}

export async function createTask(projectId: string, draft: TaskDraft): Promise<Task> {
  return send<Task>("POST", `/projects/${encodeURIComponent(projectId)}/tasks`, draft);
}

export async function moveTask(taskId: string, move: TaskMove): Promise<Task> {
  return send<Task>("POST", `/tasks/${encodeURIComponent(taskId)}/state`, move);
}

export async function fetchProgress(projectId: string): Promise<ProgressSnapshot> {
  return send<ProgressSnapshot>("GET", `/projects/${encodeURIComponent(projectId)}/progress`);
}

export async function projectHealthy(): Promise<boolean> {
  try {
    await send<unknown>("GET", "/health");
    return true;
  } catch {
    return false;
  }
}

import { PROJECT_ID, describeFailure } from "./broker.js";

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

export interface TaskDraft {
  title: string;
  kind: string;
  description: string;
}

export interface TaskMove {
  state: string;
  reason: string | null;
}

const isTask = (value: unknown): value is Task => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate["id"] === "string" &&
    typeof candidate["title"] === "string" &&
    typeof candidate["kind"] === "string" &&
    typeof candidate["state"] === "string" &&
    Array.isArray(candidate["depends_on"])
  );
};

const isProgress = (value: unknown): value is Progress => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate["task_id"] === "string" &&
    typeof candidate["percentage"] === "number" &&
    typeof candidate["criteria_total"] === "number"
  );
};

const isProgressSnapshot = (value: unknown): value is ProgressSnapshot => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate["project_id"] === "string" &&
    isProgress(candidate["overall"]) &&
    Array.isArray(candidate["per_task"])
  );
};

export async function fetchTasks(baseUrl: string): Promise<Task[]> {
  const response = await fetch(`${baseUrl}/projects/${PROJECT_ID}/tasks`);

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  return Array.isArray(parsed) ? parsed.filter(isTask) : [];
}

export async function fetchProgress(baseUrl: string): Promise<ProgressSnapshot | null> {
  const response = await fetch(`${baseUrl}/projects/${PROJECT_ID}/progress`);

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  return isProgressSnapshot(parsed) ? parsed : null;
}

export async function createTask(baseUrl: string, draft: TaskDraft): Promise<Task> {
  const response = await fetch(`${baseUrl}/projects/${PROJECT_ID}/tasks`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(draft),
  });

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!isTask(parsed)) {
    throw new Error("the created task did not match the expected shape");
  }

  return parsed;
}

export async function moveTask(baseUrl: string, taskId: string, move: TaskMove): Promise<Task> {
  const response = await fetch(`${baseUrl}/tasks/${taskId}/state`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ state: move.state, reason: move.reason, actor: "user" }),
  });

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!isTask(parsed)) {
    throw new Error("the task transition did not match the expected shape");
  }

  return parsed;
}

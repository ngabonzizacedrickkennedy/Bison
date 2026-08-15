export const PROJECT_ID = "local";

export const ROLES = ["analyst", "engine", "mediator", "inspector"] as const;

export type Role = (typeof ROLES)[number];

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

export interface CatalogEntry {
  model_id: string;
  provider: string;
  locality: string;
  size_gb: number | null;
  capability_tags: string[];
  context_window: number | null;
}

const isRoleBinding = (value: unknown): value is RoleBinding => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate["id"] === "string" &&
    typeof candidate["role"] === "string" &&
    typeof candidate["model_id"] === "string" &&
    typeof candidate["locality"] === "string"
  );
};

const isCatalogEntry = (value: unknown): value is CatalogEntry => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate["model_id"] === "string" &&
    typeof candidate["provider"] === "string" &&
    typeof candidate["locality"] === "string" &&
    Array.isArray(candidate["capability_tags"])
  );
};

export async function describeFailure(response: Response): Promise<Error> {
  try {
    const parsed: unknown = await response.json();

    if (typeof parsed === "object" && parsed !== null && "error" in parsed) {
      const detail = (parsed as { error: unknown }).error;

      if (typeof detail === "string") {
        return new Error(detail);
      }

      if (typeof detail === "object" && detail !== null && "reason" in detail) {
        const reason = (detail as { reason: unknown }).reason;
        if (typeof reason === "string") {
          return new Error(reason);
        }
      }

      return new Error(JSON.stringify(detail));
    }
  } catch {
    return new Error(`request failed: ${response.status}`);
  }

  return new Error(`request failed: ${response.status}`);
}

export async function fetchBindings(baseUrl: string): Promise<RoleBinding[]> {
  const response = await fetch(`${baseUrl}/projects/${PROJECT_ID}/bindings`);

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  return Array.isArray(parsed) ? parsed.filter(isRoleBinding) : [];
}

export async function bindRole(baseUrl: string, role: Role, modelId: string): Promise<RoleBinding> {
  const response = await fetch(`${baseUrl}/projects/${PROJECT_ID}/bindings/${role}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!isRoleBinding(parsed)) {
    throw new Error("binding response did not match the expected shape");
  }

  return parsed;
}

export async function searchCatalog(
  baseUrl: string,
  query: string,
  limit: number,
): Promise<CatalogEntry[]> {
  const search = new URLSearchParams({ q: query, limit: String(limit) });
  const response = await fetch(`${baseUrl}/catalog/search?${search.toString()}`);

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  return Array.isArray(parsed) ? parsed.filter(isCatalogEntry) : [];
}

export async function fetchInstalled(baseUrl: string): Promise<Set<string>> {
  const response = await fetch(`${baseUrl}/models`);

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!Array.isArray(parsed)) {
    return new Set();
  }

  return new Set(
    parsed
      .filter(
        (entry): entry is { model_id: string } =>
          typeof entry === "object" &&
          entry !== null &&
          typeof (entry as Record<string, unknown>)["model_id"] === "string",
      )
      .map((entry) => entry.model_id),
  );
}

export interface PullProgress {
  status: string;
  completedBytes: number | null;
  totalBytes: number | null;
  error: string | null;
}

function readProgress(line: string): PullProgress | null {
  if (line.trim() === "") {
    return null;
  }

  let parsed: unknown;

  try {
    parsed = JSON.parse(line);
  } catch {
    return null;
  }

  if (typeof parsed !== "object" || parsed === null) {
    return null;
  }

  const candidate = parsed as Record<string, unknown>;
  const completed = candidate["completed_bytes"];
  const total = candidate["total_bytes"];
  const error = candidate["error"];

  return {
    status: typeof candidate["status"] === "string" ? candidate["status"] : "",
    completedBytes: typeof completed === "number" ? completed : null,
    totalBytes: typeof total === "number" ? total : null,
    error: typeof error === "string" ? error : null,
  };
}

export async function pullModel(
  baseUrl: string,
  modelId: string,
  onProgress: (progress: PullProgress) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${baseUrl}/models/pull/${modelId}`, { method: "POST", signal });

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const body = response.body;

  if (body === null) {
    throw new Error("the pull returned no stream");
  }

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const progress = readProgress(line);

      if (progress === null) {
        continue;
      }

      if (progress.error !== null) {
        throw new Error(progress.error);
      }

      onProgress(progress);
    }
  }
}

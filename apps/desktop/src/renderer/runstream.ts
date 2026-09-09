import { PROJECT_ID, describeFailure } from "./broker";

const REQUEST_ID_HEADER = "x-bison-request-id";

type FieldKind = "string" | "number" | "string?" | "number?" | "strings";

const SPECS = {
  run_started: { order: "strings", tasks_total: "number" },
  task_started: { task_id: "string", title: "string", position: "number", tasks_total: "number" },
  plan_ready: {
    task_id: "string",
    plan_id: "string",
    steps_total: "number",
    gated_total: "number",
  },
  task_replanning: {
    task_id: "string",
    superseded_plan_id: "string",
    attempt: "number",
    attempts_allowed: "number",
    reason: "string",
  },
  step_awaiting_confirmation: {
    task_id: "string",
    step_id: "string",
    position: "number",
    description: "string",
    reason: "string?",
  },
  step_started: {
    task_id: "string",
    step_id: "string",
    position: "number",
    description: "string",
  },
  step_output: {
    task_id: "string",
    step_id: "string",
    stream: "string",
    step_sequence: "number",
    text: "string",
  },
  step_finished: {
    task_id: "string",
    step_id: "string",
    state: "string",
    exit_code: "number?",
    terminated_by: "string?",
    error_message: "string?",
  },
  criterion_settled: {
    task_id: "string",
    criterion_id: "string",
    statement: "string",
    status: "string",
    detail: "string",
  },
  task_finished: {
    task_id: "string",
    state: "string",
    reason: "string?",
    task_percentage: "number",
    project_percentage: "number",
  },
  halted: { reason: "string", task_id: "string?", record_id: "string?" },
  run_finished: {
    tasks_completed: "number",
    tasks_failed: "number",
    tasks_total: "number",
    project_percentage: "number",
  },
  error: { task_id: "string?", detail: "string" },
} as const satisfies Record<string, Record<string, FieldKind>>;

type Field<K extends FieldKind> = K extends "string"
  ? string
  : K extends "number"
    ? number
    : K extends "string?"
      ? string | null
      : K extends "number?"
        ? number | null
        : string[];

type Payload<S> = { [K in keyof S]: S[K] extends FieldKind ? Field<S[K]> : never };

export interface RunEnvelope {
  request_id: string;
  project_id: string;
  sequence: number;
}

export type RunEventName = keyof typeof SPECS;

export type RunEvent = {
  [K in RunEventName]: RunEnvelope & { event: K } & Payload<(typeof SPECS)[K]>;
}[RunEventName];

export interface RunStream {
  requestId: string;
  drain: (onEvent: (event: RunEvent) => void) => Promise<void>;
}

const TERMINAL: ReadonlySet<RunEventName> = new Set<RunEventName>([
  "run_finished",
  "halted",
  "error",
]);

export function isTerminal(event: RunEvent): boolean {
  return TERMINAL.has(event.event);
}

function coerce(kind: FieldKind, value: unknown): string | number | string[] | null | undefined {
  switch (kind) {
    case "string":
      return typeof value === "string" ? value : undefined;
    case "number":
      return typeof value === "number" && Number.isFinite(value) ? value : undefined;
    case "string?":
      if (value === null) {
        return null;
      }
      return typeof value === "string" ? value : undefined;
    case "number?":
      if (value === null) {
        return null;
      }
      return typeof value === "number" && Number.isFinite(value) ? value : undefined;
    case "strings":
      return Array.isArray(value) && value.every((entry) => typeof entry === "string")
        ? (value as string[])
        : undefined;
  }
}

function readEnvelope(candidate: Record<string, unknown>): RunEnvelope | null {
  const requestId = candidate["request_id"];
  const projectId = candidate["project_id"];
  const sequence = candidate["sequence"];

  if (
    typeof requestId !== "string" ||
    typeof projectId !== "string" ||
    typeof sequence !== "number"
  ) {
    return null;
  }

  return { request_id: requestId, project_id: projectId, sequence };
}

function decode(line: string): RunEvent | null {
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
  const name = candidate["event"];

  if (typeof name !== "string" || !(name in SPECS)) {
    return null;
  }

  const envelope = readEnvelope(candidate);

  if (envelope === null) {
    return null;
  }

  const spec: Record<string, FieldKind> = SPECS[name as RunEventName];
  const payload: Record<string, unknown> = {};

  for (const [key, kind] of Object.entries(spec)) {
    const value = coerce(kind, candidate[key]);

    if (value === undefined) {
      return null;
    }

    payload[key] = value;
  }

  return { ...envelope, ...payload, event: name } as RunEvent;
}

async function drain(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: RunEvent) => void,
): Promise<void> {
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
      const event = decode(line);

      if (event !== null) {
        onEvent(event);
      }
    }
  }

  const trailing = decode(buffer);

  if (trailing !== null) {
    onEvent(trailing);
  }
}

async function open(url: string, signal: AbortSignal): Promise<RunStream> {
  const response = await fetch(url, {
    method: "POST",
    headers: { accept: "application/x-ndjson" },
    signal,
  });

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const requestId = response.headers.get(REQUEST_ID_HEADER);

  if (requestId === null) {
    throw new Error(`the gateway returned no ${REQUEST_ID_HEADER} header`);
  }

  const body = response.body;

  if (body === null) {
    throw new Error("the gateway returned no stream");
  }

  return { requestId, drain: (onEvent) => drain(body, onEvent) };
}

export async function openRun(baseUrl: string, signal: AbortSignal): Promise<RunStream> {
  return open(`${baseUrl}/projects/${PROJECT_ID}/run`, signal);
}

export async function openConfirm(
  baseUrl: string,
  stepId: string,
  signal: AbortSignal,
): Promise<RunStream> {
  return open(`${baseUrl}/steps/${encodeURIComponent(stepId)}/confirm`, signal);
}

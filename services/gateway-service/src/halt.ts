import { randomUUID } from "node:crypto";
import { request } from "undici";
import { config } from "./config.js";

export type HaltReason = "kill_switch" | "step_failure" | "project_switch" | "user_stop";

export const HALT_REASONS: readonly HaltReason[] = [
  "kill_switch",
  "step_failure",
  "project_switch",
  "user_stop",
];

export interface HaltRecipient {
  service: string;
  url: string;
}

export interface RecipientAcknowledgement {
  service: string;
  acknowledged: boolean;
  status: number | null;
  detail: string | null;
  latency_ms: number;
}

export interface HaltSignal {
  id: string;
  reason: HaltReason;
  request_id: string | null;
  project_id: string | null;
  task_id: string | null;
  issued_at: string;
  recipients: RecipientAcknowledgement[];
  acknowledged_count: number;
  silent_count: number;
}

export interface RecipientHaltState {
  service: string;
  reachable: boolean;
  halted: boolean | null;
  boundary: string | null;
  reason: HaltReason | null;
  signal_id: string | null;
  halted_at: string | null;
  status: number | null;
  detail: string | null;
  latency_ms: number;
}

export interface HaltStateReport {
  halted: boolean;
  halted_count: number;
  reachable_count: number;
  silent_count: number;
  recipients: RecipientHaltState[];
}

export interface RecipientResume {
  service: string;
  resumed: boolean;
  status: number | null;
  detail: string | null;
  latency_ms: number;
}

export interface ResumeReport {
  actor: string;
  resumed: boolean;
  resumed_count: number;
  silent_count: number;
  recipients: RecipientResume[];
}

export interface HaltInstruction {
  reason: HaltReason;
  requestId?: string | null;
  projectId?: string | null;
  taskId?: string | null;
}

export const recipients: readonly HaltRecipient[] = [
  { service: "automation-service", url: config.automationUrl },
  { service: "task-runner-service", url: config.taskRunnerUrl },
  { service: "dev-env-service", url: config.devEnvUrl },
  { service: "mediator-service", url: config.mediatorUrl },
];

export function isHaltReason(value: unknown): value is HaltReason {
  return typeof value === "string" && HALT_REASONS.includes(value as HaltReason);
}

function describe(error: unknown): string {
  if (error instanceof Error) {
    const cause = (error as { cause?: { code?: string } }).cause;
    return cause?.code ?? error.message;
  }

  return String(error);
}

interface Reached {
  ok: boolean;
  status: number | null;
  payload: Record<string, unknown> | null;
  detail: string | null;
  latency_ms: number;
}

async function reach(url: string, method: "GET" | "POST", body?: unknown): Promise<Reached> {
  const started = Date.now();
  const carried = body === undefined ? null : JSON.stringify(body);

  try {
    const response = await request(url, {
      method,
      headers: carried === null ? {} : { "content-type": "application/json" },
      body: carried,
      signal: AbortSignal.timeout(config.haltTimeoutMs),
    });

    const text = await response.body.text();
    let payload: Record<string, unknown> | null = null;

    try {
      const parsed: unknown = JSON.parse(text);
      payload =
        typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : null;
    } catch {
      payload = null;
    }

    return {
      ok: response.statusCode >= 200 && response.statusCode < 300,
      status: response.statusCode,
      payload,
      detail: null,
      latency_ms: Date.now() - started,
    };
  } catch (error) {
    return {
      ok: false,
      status: null,
      payload: null,
      detail: describe(error),
      latency_ms: Date.now() - started,
    };
  }
}

function bool(payload: Record<string, unknown> | null, key: string): boolean | null {
  const value = payload?.[key];

  return typeof value === "boolean" ? value : null;
}

function str(payload: Record<string, unknown> | null, key: string): string | null {
  const value = payload?.[key];

  return typeof value === "string" ? value : null;
}

async function notify(
  recipient: HaltRecipient,
  signal: Omit<HaltSignal, "recipients" | "acknowledged_count" | "silent_count">,
): Promise<RecipientAcknowledgement> {
  const reached = await reach(`${recipient.url}/halt`, "POST", {
    id: signal.id,
    reason: signal.reason,
    request_id: signal.request_id,
    project_id: signal.project_id,
    task_id: signal.task_id,
    issued_at: signal.issued_at,
  });

  return {
    service: recipient.service,
    acknowledged: reached.ok,
    status: reached.status,
    detail: reached.detail,
    latency_ms: reached.latency_ms,
  };
}

async function probe(recipient: HaltRecipient): Promise<RecipientHaltState> {
  const reached = await reach(`${recipient.url}/halt/state`, "GET");
  const signal = reached.payload?.["signal"];
  const carried =
    typeof signal === "object" && signal !== null ? (signal as Record<string, unknown>) : null;
  const reason = str(carried, "reason");

  return {
    service: recipient.service,
    reachable: reached.ok,
    halted: reached.ok ? bool(reached.payload, "halted") : null,
    boundary: str(reached.payload, "boundary"),
    reason: isHaltReason(reason) ? reason : null,
    signal_id: str(carried, "id"),
    halted_at: str(reached.payload, "halted_at"),
    status: reached.status,
    detail: reached.detail,
    latency_ms: reached.latency_ms,
  };
}

async function revive(recipient: HaltRecipient, actor: string): Promise<RecipientResume> {
  const reached = await reach(`${recipient.url}/halt/resume`, "POST", { actor });

  return {
    service: recipient.service,
    resumed: reached.ok,
    status: reached.status,
    detail: reached.detail,
    latency_ms: reached.latency_ms,
  };
}

export async function readState(
  targets: readonly HaltRecipient[] = recipients,
): Promise<HaltStateReport> {
  const settled = await Promise.all(targets.map((target) => probe(target)));
  const halted = settled.filter((entry) => entry.halted === true);

  return {
    halted: halted.length > 0,
    halted_count: halted.length,
    reachable_count: settled.filter((entry) => entry.reachable).length,
    silent_count: settled.filter((entry) => !entry.reachable).length,
    recipients: settled,
  };
}

export async function resumeAll(
  actor: string,
  targets: readonly HaltRecipient[] = recipients,
): Promise<ResumeReport> {
  const settled = await Promise.all(targets.map((target) => revive(target, actor)));
  const resumed = settled.filter((entry) => entry.resumed);

  return {
    actor,
    resumed: resumed.length === settled.length,
    resumed_count: resumed.length,
    silent_count: settled.length - resumed.length,
    recipients: settled,
  };
}

export async function broadcast(
  instruction: HaltInstruction,
  targets: readonly HaltRecipient[] = recipients,
): Promise<HaltSignal> {
  const issued = {
    id: randomUUID(),
    reason: instruction.reason,
    request_id: instruction.requestId ?? null,
    project_id: instruction.projectId ?? null,
    task_id: instruction.taskId ?? null,
    issued_at: new Date().toISOString(),
  };

  const settled = await Promise.all(targets.map((target) => notify(target, issued)));

  return {
    ...issued,
    recipients: settled,
    acknowledged_count: settled.filter((entry) => entry.acknowledged).length,
    silent_count: settled.filter((entry) => !entry.acknowledged).length,
  };
}

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

async function notify(
  recipient: HaltRecipient,
  signal: Omit<HaltSignal, "recipients" | "acknowledged_count" | "silent_count">,
): Promise<RecipientAcknowledgement> {
  const started = Date.now();

  try {
    const response = await request(`${recipient.url}/halt`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: signal.id,
        reason: signal.reason,
        request_id: signal.request_id,
        project_id: signal.project_id,
        task_id: signal.task_id,
        issued_at: signal.issued_at,
      }),
      signal: AbortSignal.timeout(config.haltTimeoutMs),
    });

    await response.body.dump();

    return {
      service: recipient.service,
      acknowledged: response.statusCode >= 200 && response.statusCode < 300,
      status: response.statusCode,
      detail: null,
      latency_ms: Date.now() - started,
    };
  } catch (error) {
    return {
      service: recipient.service,
      acknowledged: false,
      status: null,
      detail: describe(error),
      latency_ms: Date.now() - started,
    };
  }
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

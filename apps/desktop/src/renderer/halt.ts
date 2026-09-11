import { describeFailure } from "./broker";

export const HALT_REASONS = ["kill_switch", "step_failure", "project_switch", "user_stop"] as const;

export type HaltReason = (typeof HALT_REASONS)[number];

export const STOP_REASON: HaltReason = "user_stop";

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

const asRecord = (value: unknown): Record<string, unknown> | null => {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
};

export const isHaltReason = (value: unknown): value is HaltReason => {
  return typeof value === "string" && HALT_REASONS.includes(value as HaltReason);
};

export const isHaltSignal = (value: unknown): value is HaltSignal => {
  const candidate = asRecord(value);

  if (candidate === null) {
    return false;
  }

  return (
    typeof candidate["id"] === "string" &&
    isHaltReason(candidate["reason"]) &&
    typeof candidate["issued_at"] === "string" &&
    typeof candidate["acknowledged_count"] === "number" &&
    typeof candidate["silent_count"] === "number" &&
    Array.isArray(candidate["recipients"])
  );
};

export const isHaltStateReport = (value: unknown): value is HaltStateReport => {
  const candidate = asRecord(value);

  if (candidate === null) {
    return false;
  }

  return (
    typeof candidate["halted"] === "boolean" &&
    typeof candidate["halted_count"] === "number" &&
    typeof candidate["reachable_count"] === "number" &&
    typeof candidate["silent_count"] === "number" &&
    Array.isArray(candidate["recipients"])
  );
};

export const isResumeReport = (value: unknown): value is ResumeReport => {
  const candidate = asRecord(value);

  if (candidate === null) {
    return false;
  }

  return (
    typeof candidate["actor"] === "string" &&
    typeof candidate["resumed"] === "boolean" &&
    typeof candidate["resumed_count"] === "number" &&
    typeof candidate["silent_count"] === "number" &&
    Array.isArray(candidate["recipients"])
  );
};

export function describeReach(report: HaltStateReport): string {
  const total = report.reachable_count + report.silent_count;

  return `${report.reachable_count} of ${total} answered`;
}

export function haltedServices(report: HaltStateReport): string[] {
  return report.recipients.filter((entry) => entry.halted === true).map((entry) => entry.service);
}

export function silentServices(report: HaltStateReport): string[] {
  return report.recipients.filter((entry) => !entry.reachable).map((entry) => entry.service);
}

export function firstHaltReason(report: HaltStateReport): HaltReason | null {
  const halted = report.recipients.find((entry) => entry.halted === true && entry.reason !== null);

  return halted?.reason ?? null;
}

export async function fetchHaltState(baseUrl: string): Promise<HaltStateReport> {
  const response = await fetch(`${baseUrl}/halt/state`);

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!isHaltStateReport(parsed)) {
    throw new Error("halt state response did not match the expected shape");
  }

  return parsed;
}

export async function requestStop(baseUrl: string): Promise<HaltSignal> {
  const response = await fetch(`${baseUrl}/halt`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ reason: STOP_REASON }),
  });

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!isHaltSignal(parsed)) {
    throw new Error("halt response did not match the expected shape");
  }

  return parsed;
}

export async function requestResume(baseUrl: string, actor = "user"): Promise<ResumeReport> {
  const response = await fetch(`${baseUrl}/halt/resume`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ actor }),
  });

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!isResumeReport(parsed)) {
    throw new Error("resume response did not match the expected shape");
  }

  return parsed;
}

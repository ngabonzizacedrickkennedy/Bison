export type HaltReason = "kill_switch" | "step_failure" | "project_switch" | "user_stop";

export type Boundary = "immediate" | "between_actions" | "between_tasks";

export const BOUNDARY_MEANING: Record<Boundary, string> = {
  immediate: "the process tree is killed without waiting",
  between_actions: "the action in flight completes, then nothing further starts",
  between_tasks: "the task in flight completes, then nothing further starts",
};

const REASONS: readonly HaltReason[] = [
  "kill_switch",
  "step_failure",
  "project_switch",
  "user_stop",
];

export interface HaltSignal {
  id: string;
  reason: HaltReason;
  request_id: string | null;
  project_id: string | null;
  task_id: string | null;
  issued_at: string;
}

export interface HaltAcknowledgement {
  service: string;
  boundary: Boundary;
  boundary_meaning: string;
  halted: boolean;
  signal_id: string;
  reason: HaltReason;
  accepted_at: string;
  signals_received: number;
  already_halted: boolean;
}

export interface HaltStatus {
  service: string;
  boundary: Boundary;
  boundary_meaning: string;
  halted: boolean;
  signal: HaltSignal | null;
  signals_received: number;
  halted_at: string | null;
  resumed_at: string | null;
  resumed_by: string | null;
}

export class HaltedError extends Error {
  constructor(
    readonly service: string,
    readonly signal: HaltSignal,
  ) {
    super(`${service} is halted by ${signal.reason} and accepts no new work`);
    this.name = "HaltedError";
  }
}

export function parseSignal(body: unknown): HaltSignal {
  const candidate = body as Partial<Record<keyof HaltSignal, unknown>> | null;

  const id = candidate?.id;
  const reason = candidate?.reason;
  const issuedAt = candidate?.issued_at;

  if (typeof id !== "string" || id.length === 0) {
    throw new TypeError("halt signal requires a non-empty id");
  }

  if (typeof reason !== "string" || !REASONS.includes(reason as HaltReason)) {
    throw new TypeError(`unknown halt reason "${String(reason)}"`);
  }

  if (typeof issuedAt !== "string" || Number.isNaN(Date.parse(issuedAt))) {
    throw new TypeError("halt signal requires an issued_at timestamp");
  }

  return {
    id,
    reason: reason as HaltReason,
    request_id: typeof candidate?.request_id === "string" ? candidate.request_id : null,
    project_id: typeof candidate?.project_id === "string" ? candidate.project_id : null,
    task_id: typeof candidate?.task_id === "string" ? candidate.task_id : null,
    issued_at: issuedAt,
  };
}

export class HaltState {
  private readonly signals: HaltSignal[] = [];
  private stopped = false;
  private haltedAt: string | null = null;
  private resumedAt: string | null = null;
  private resumedBy: string | null = null;

  constructor(
    private readonly service: string,
    private readonly boundary: Boundary,
  ) {}

  get halted(): boolean {
    return this.stopped;
  }

  get signal(): HaltSignal | null {
    return this.signals.at(-1) ?? null;
  }

  accept(signal: HaltSignal): HaltAcknowledgement {
    const already = this.stopped;
    const now = new Date().toISOString();

    this.signals.push(signal);
    this.stopped = true;

    if (!already) {
      this.haltedAt = now;
      this.resumedAt = null;
      this.resumedBy = null;
    }

    return {
      service: this.service,
      boundary: this.boundary,
      boundary_meaning: BOUNDARY_MEANING[this.boundary],
      halted: true,
      signal_id: signal.id,
      reason: signal.reason,
      accepted_at: now,
      signals_received: this.signals.length,
      already_halted: already,
    };
  }

  resume(actor: string): HaltStatus {
    this.stopped = false;
    this.resumedAt = new Date().toISOString();
    this.resumedBy = actor;

    return this.status();
  }

  guard(): void {
    const current = this.signals.at(-1);

    if (this.stopped && current) {
      throw new HaltedError(this.service, current);
    }
  }

  status(): HaltStatus {
    return {
      service: this.service,
      boundary: this.boundary,
      boundary_meaning: BOUNDARY_MEANING[this.boundary],
      halted: this.stopped,
      signal: this.signal,
      signals_received: this.signals.length,
      halted_at: this.haltedAt,
      resumed_at: this.resumedAt,
      resumed_by: this.resumedBy,
    };
  }
}

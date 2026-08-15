export type Activity =
  | { phase: "idle" }
  | { phase: "invoking"; role: string; modelId: string; locality: string }
  | { phase: "answered"; modelId: string; latencyMs: number; failedOverFrom: string | null }
  | { phase: "failed"; reason: string };

export const IDLE: Activity = { phase: "idle" };

export function readInvoking(payload: unknown): Activity | null {
  if (typeof payload !== "object" || payload === null) {
    return null;
  }

  const candidate = payload as Record<string, unknown>;

  if (
    typeof candidate["role"] !== "string" ||
    typeof candidate["model_id"] !== "string" ||
    typeof candidate["locality"] !== "string"
  ) {
    return null;
  }

  return {
    phase: "invoking",
    role: candidate["role"],
    modelId: candidate["model_id"],
    locality: candidate["locality"],
  };
}

export function readAnswered(payload: unknown): Activity | null {
  if (typeof payload !== "object" || payload === null) {
    return null;
  }

  const candidate = payload as Record<string, unknown>;

  if (typeof candidate["model_id"] !== "string" || typeof candidate["latency_ms"] !== "number") {
    return null;
  }

  const failedOverFrom = candidate["failed_over_from"];

  return {
    phase: "answered",
    modelId: candidate["model_id"],
    latencyMs: candidate["latency_ms"],
    failedOverFrom: typeof failedOverFrom === "string" ? failedOverFrom : null,
  };
}

function detailText(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }

  if (typeof detail === "object" && detail !== null && "reason" in detail) {
    const reason = (detail as { reason: unknown }).reason;
    return typeof reason === "string" ? reason : null;
  }

  return null;
}

export function readFailure(payload: unknown): Activity {
  if (typeof payload === "object" && payload !== null) {
    const candidate = payload as Record<string, unknown>;
    const detail = detailText(candidate["detail"]);

    if (detail !== null) {
      return { phase: "failed", reason: detail };
    }

    if (typeof candidate["reason"] === "string") {
      return { phase: "failed", reason: candidate["reason"] };
    }
  }

  return { phase: "failed", reason: "the request failed" };
}

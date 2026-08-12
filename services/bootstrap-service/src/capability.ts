import type { CapabilityStrength } from "@bison/contracts";

export interface Capability<T extends string> {
  backend: T | null;
  strength: CapabilityStrength;
  available: T[];
}

export interface BackendProbe<T extends string> {
  backend: T;
  strength: CapabilityStrength;
  works: () => Promise<boolean>;
}

export async function probeCapability<T extends string>(
  candidates: readonly BackendProbe<T>[],
): Promise<Capability<T>> {
  const outcomes = await Promise.all(
    candidates.map(async (candidate) => ({ candidate, passed: await candidate.works() })),
  );

  const passed = outcomes.filter((outcome) => outcome.passed).map((outcome) => outcome.candidate);
  const strongest = passed[0];

  if (strongest === undefined) {
    return { backend: null, strength: "unavailable", available: [] };
  }

  return {
    backend: strongest.backend,
    strength: strongest.strength,
    available: passed.map((candidate) => candidate.backend),
  };
}

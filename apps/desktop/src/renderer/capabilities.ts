export interface Capability {
  backend: string | null;
  strength: string;
  available: string[];
}

export interface CapabilityManifest {
  schema_version: number;
  generated_at: string;
  sandbox: Capability;
  secrets: Capability;
  ocr: Capability;
  database: Capability;
  cache: Capability;
  input_injection: Capability;
  screen_capture: Capability;
  hardware: {
    ram_gb: number;
    free_disk_gb: number;
    cpu_cores: number;
    os_version: string;
  };
  budgets: {
    local_model_gb: number;
    max_projects: number;
  };
}

export const CAPABILITY_NAMES = [
  "sandbox",
  "secrets",
  "ocr",
  "database",
  "cache",
  "input_injection",
  "screen_capture",
] as const;

export type CapabilityName = (typeof CAPABILITY_NAMES)[number];

const isCapability = (value: unknown): value is Capability => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    (candidate["backend"] === null || typeof candidate["backend"] === "string") &&
    typeof candidate["strength"] === "string" &&
    Array.isArray(candidate["available"])
  );
};

const isManifest = (value: unknown): value is CapabilityManifest => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;

  if (typeof candidate["generated_at"] !== "string") {
    return false;
  }

  return CAPABILITY_NAMES.every((name) => isCapability(candidate[name]));
};

export function isDegraded(capability: Capability): boolean {
  return capability.strength !== "full" && capability.strength !== "verified";
}

export async function fetchManifest(baseUrl: string): Promise<CapabilityManifest> {
  const response = await fetch(`${baseUrl}/manifest`);

  if (!response.ok) {
    throw new Error(`manifest request failed: ${response.status}`);
  }

  const parsed: unknown = await response.json();

  if (!isManifest(parsed)) {
    throw new Error("manifest response did not match the expected shape");
  }

  return parsed;
}

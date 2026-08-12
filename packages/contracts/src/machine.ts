import { z } from "zod";

export const CapabilityStrengthSchema = z.enum([
  "full",
  "medium",
  "weak",
  "verified",
  "unverified",
  "unavailable",
]);

export const SandboxBackendSchema = z.enum(["docker", "job_object", "wasm"]);
export const SecretsBackendSchema = z.enum(["keytar", "age_file"]);
export const OcrBackendSchema = z.enum(["tesseract_bundled", "tesseract_system"]);
export const DatabaseBackendSchema = z.enum(["sqlite", "postgres"]);
export const CacheBackendSchema = z.enum(["in_process", "redis"]);
export const InputInjectionBackendSchema = z.enum(["pyautogui"]);
export const ScreenCaptureBackendSchema = z.enum(["mss"]);

const capability = <T extends z.ZodTypeAny>(backend: T) =>
  z.object({
    backend: backend.nullable(),
    strength: CapabilityStrengthSchema,
    available: z.array(backend),
  });

export const HardwareProfileSchema = z.object({
  ram_gb: z.number().positive(),
  free_disk_gb: z.number().nonnegative(),
  cpu_cores: z.number().int().positive(),
  os_version: z.string(),
});

export const BudgetsSchema = z.object({
  local_model_gb: z.number().nonnegative(),
  max_projects: z.number().int().positive(),
});

export const CapabilityManifestSchema = z.object({
  schema_version: z.literal(1),
  generated_at: z.string().datetime({ offset: true }),
  sandbox: capability(SandboxBackendSchema),
  secrets: capability(SecretsBackendSchema),
  ocr: capability(OcrBackendSchema),
  database: capability(DatabaseBackendSchema),
  cache: capability(CacheBackendSchema),
  input_injection: capability(InputInjectionBackendSchema),
  screen_capture: capability(ScreenCaptureBackendSchema),
  hardware: HardwareProfileSchema,
  budgets: BudgetsSchema,
});

export type CapabilityStrength = z.infer<typeof CapabilityStrengthSchema>;
export type SandboxBackend = z.infer<typeof SandboxBackendSchema>;
export type SecretsBackend = z.infer<typeof SecretsBackendSchema>;
export type OcrBackend = z.infer<typeof OcrBackendSchema>;
export type DatabaseBackend = z.infer<typeof DatabaseBackendSchema>;
export type CacheBackend = z.infer<typeof CacheBackendSchema>;
export type InputInjectionBackend = z.infer<typeof InputInjectionBackendSchema>;
export type ScreenCaptureBackend = z.infer<typeof ScreenCaptureBackendSchema>;
export type HardwareProfile = z.infer<typeof HardwareProfileSchema>;
export type Budgets = z.infer<typeof BudgetsSchema>;
export type CapabilityManifest = z.infer<typeof CapabilityManifestSchema>;

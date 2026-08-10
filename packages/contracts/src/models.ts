import { z } from "zod";
import { IdSchema, NonEmptyStringSchema, TimestampSchema, UrlSchema } from "./primitives.js";

export const ModelRoleSchema = z.enum(["analyst", "engine", "mediator", "inspector"]);

export const LocalitySchema = z.enum(["local", "remote"]);

export const AuthBackendSchema = z.enum(["api_key", "browser_session"]);

export const EngineStatusSchema = z.enum([
  "active",
  "unconfigured",
  "key_invalid",
  "needs_relogin",
  "unreachable",
]);

export const EngineDescriptorSchema = z.object({
  engine_id: IdSchema,
  label: NonEmptyStringSchema.max(80),
  base_url: UrlSchema,
  auth_backend: AuthBackendSchema.nullable(),
  secret_ref: NonEmptyStringSchema.nullable(),
  status: EngineStatusSchema,
  chat_url: UrlSchema.nullable(),
  created_at: TimestampSchema,
  last_validated_at: TimestampSchema.nullable(),
});

export const ModelDescriptorSchema = z.object({
  model_id: NonEmptyStringSchema,
  provider: NonEmptyStringSchema,
  locality: LocalitySchema,
  size_gb: z.number().nonnegative().nullable(),
  context_window: z.number().int().positive().nullable(),
  installed: z.boolean(),
});

export const CatalogEntrySchema = z.object({
  model_id: NonEmptyStringSchema,
  provider: NonEmptyStringSchema,
  locality: LocalitySchema,
  size_gb: z.number().nonnegative().nullable(),
  capability_tags: z.array(NonEmptyStringSchema),
  context_window: z.number().int().positive().nullable(),
  indexed_at: TimestampSchema,
});

export const RoleBindingSchema = z.object({
  id: IdSchema,
  project_id: IdSchema,
  role: ModelRoleSchema,
  model_id: NonEmptyStringSchema,
  engine_id: IdSchema.nullable(),
  locality: LocalitySchema,
  prompt_version: NonEmptyStringSchema,
  bound_at: TimestampSchema,
});

export const InvokeModeSchema = z.enum(["completion", "structured"]);

export const InvokeRequestSchema = z.object({
  request_id: IdSchema,
  model_id: NonEmptyStringSchema,
  engine_id: IdSchema.nullable(),
  role: ModelRoleSchema,
  prompt: NonEmptyStringSchema,
  mode: InvokeModeSchema,
  schema_name: NonEmptyStringSchema.nullable(),
  timeout_ms: z.number().int().positive(),
});

export const InvokeResponseSchema = z.object({
  request_id: IdSchema,
  model_id: NonEmptyStringSchema,
  engine_id: IdSchema.nullable(),
  response: z.string(),
  failed_over_from: NonEmptyStringSchema.nullable(),
  latency_ms: z.number().int().nonnegative(),
  completed_at: TimestampSchema,
});

export type ModelRole = z.infer<typeof ModelRoleSchema>;
export type Locality = z.infer<typeof LocalitySchema>;
export type AuthBackend = z.infer<typeof AuthBackendSchema>;
export type EngineStatus = z.infer<typeof EngineStatusSchema>;
export type EngineDescriptor = z.infer<typeof EngineDescriptorSchema>;
export type ModelDescriptor = z.infer<typeof ModelDescriptorSchema>;
export type CatalogEntry = z.infer<typeof CatalogEntrySchema>;
export type RoleBinding = z.infer<typeof RoleBindingSchema>;
export type InvokeMode = z.infer<typeof InvokeModeSchema>;
export type InvokeRequest = z.infer<typeof InvokeRequestSchema>;
export type InvokeResponse = z.infer<typeof InvokeResponseSchema>;

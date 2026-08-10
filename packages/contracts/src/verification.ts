import { z } from "zod";
import {
  ConfidenceSchema,
  HashSchema,
  IdSchema,
  NonEmptyStringSchema,
  TimestampSchema,
} from "./primitives.js";

export const VerdictSchema = z.enum(["verified", "failed", "inconclusive"]);

export const EvidenceKindSchema = z.enum([
  "screenshot",
  "ocr_text",
  "stdout",
  "file_hash",
  "http_response",
  "sql_result",
  "window_state",
]);

export const EvidenceRefSchema = z.object({
  id: IdSchema,
  criterion_id: IdSchema,
  step_id: IdSchema.nullable(),
  kind: EvidenceKindSchema,
  ref: NonEmptyStringSchema,
  content_hash: HashSchema.nullable(),
  excerpt: z.string().nullable(),
  captured_at: TimestampSchema,
});

export const InspectionResultSchema = z.object({
  id: IdSchema,
  criterion_id: IdSchema,
  task_id: IdSchema,
  verdict: VerdictSchema,
  check_kind_used: z.enum(["deterministic", "inspected"]),
  confidence: ConfidenceSchema.nullable(),
  reasoning: z.string().nullable(),
  evidence: z.array(EvidenceRefSchema),
  prompt_version: NonEmptyStringSchema.nullable(),
  model_id: NonEmptyStringSchema.nullable(),
  inspected_at: TimestampSchema,
});

export const NarrationEventSchema = z.object({
  id: IdSchema,
  request_id: IdSchema,
  step_id: IdSchema.nullable(),
  criterion_id: IdSchema.nullable(),
  text: NonEmptyStringSchema.max(500),
  emitted_at: TimestampSchema,
});

export type Verdict = z.infer<typeof VerdictSchema>;
export type EvidenceKind = z.infer<typeof EvidenceKindSchema>;
export type EvidenceRef = z.infer<typeof EvidenceRefSchema>;
export type InspectionResult = z.infer<typeof InspectionResultSchema>;
export type NarrationEvent = z.infer<typeof NarrationEventSchema>;

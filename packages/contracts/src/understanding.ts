import { z } from "zod";
import {
  ConfidenceSchema,
  IdSchema,
  NonEmptyStringSchema,
  TimestampSchema,
  UrlSchema,
} from "./primitives.js";
import { ProjectTypeSchema } from "./project.js";

export const AnswerKindSchema = z.enum(["text", "choice", "file", "image", "link", "confirm"]);

export const ProjectBriefSchema = z.object({
  id: IdSchema,
  project_id: IdSchema,
  round: z.number().int().positive(),
  conceive_revision_number: z.number().int().nonnegative(),
  summary: NonEmptyStringSchema.max(2000),
  interpreted_goal: NonEmptyStringSchema.max(1000),
  project_type: ProjectTypeSchema,
  known_constraints: z.array(z.string()),
  assumptions: z.array(z.string()),
  out_of_scope: z.array(z.string()),
  seeded_success_criteria: z.array(z.string()),
  confidence: ConfidenceSchema,
  unresolved_fields: z.array(z.string()),
  prompt_version: NonEmptyStringSchema,
  model_id: NonEmptyStringSchema,
  created_at: TimestampSchema,
});

export const ClarificationQuestionSchema = z.object({
  id: IdSchema,
  text: NonEmptyStringSchema.max(500),
  why_asked: NonEmptyStringSchema.max(500),
  answer_kind: AnswerKindSchema,
  choices: z.array(NonEmptyStringSchema).nullable(),
  allow_attachments: z.boolean(),
});

export const ClarificationRequestSchema = z.object({
  id: IdSchema,
  project_id: IdSchema,
  task_id: IdSchema.nullable(),
  round: z.number().int().positive(),
  blocking: z.boolean(),
  confidence: ConfidenceSchema,
  questions: z.array(ClarificationQuestionSchema).min(1),
  created_at: TimestampSchema,
  answered_at: TimestampSchema.nullable(),
});

export const ClarificationAttachmentSchema = z.object({
  id: IdSchema,
  kind: z.enum(["file", "image", "link"]),
  path: z.string().nullable(),
  url: UrlSchema.nullable(),
  caption: z.string().nullable(),
});

export const ClarificationAnswerSchema = z.object({
  id: IdSchema,
  request_id: IdSchema,
  question_id: IdSchema,
  text: z.string().nullable(),
  choice: z.string().nullable(),
  confirmed: z.boolean().nullable(),
  attachments: z.array(ClarificationAttachmentSchema),
  answered_at: TimestampSchema,
});

export type AnswerKind = z.infer<typeof AnswerKindSchema>;
export type ProjectBrief = z.infer<typeof ProjectBriefSchema>;
export type ClarificationQuestion = z.infer<typeof ClarificationQuestionSchema>;
export type ClarificationRequest = z.infer<typeof ClarificationRequestSchema>;
export type ClarificationAnswer = z.infer<typeof ClarificationAnswerSchema>;

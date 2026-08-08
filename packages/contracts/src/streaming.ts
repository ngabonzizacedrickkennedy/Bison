import { z } from 'zod';
import { IdSchema, NonEmptyStringSchema, TimestampSchema } from './primitives.js';

export const LiveEventTypeSchema = z.enum([
  'message',
  'plan_created',
  'step_state_changed',
  'confirmation_required',
  'script_output',
  'window_state',
  'automation_action',
  'narration',
  'criterion_settled',
  'progress_updated',
  'clarification_required',
  'halt',
  'error',
]);

export const LiveEventSchema = z.object({
  id: IdSchema,
  request_id: IdSchema,
  project_id: IdSchema.nullable(),
  task_id: IdSchema.nullable(),
  step_id: IdSchema.nullable(),
  event_type: LiveEventTypeSchema,
  sequence: z.number().int().nonnegative(),
  payload: z.unknown(),
  emitted_at: TimestampSchema,
});

export const MessageRoleSchema = z.enum(['user', 'assistant', 'system']);

export const MessageSchema = z.object({
  id: IdSchema,
  request_id: IdSchema,
  project_id: IdSchema.nullable(),
  task_id: IdSchema.nullable(),
  role: MessageRoleSchema,
  content: z.string(),
  created_at: TimestampSchema,
});

export const ExecutionLogKindSchema = z.enum([
  'task_transition',
  'step_transition',
  'model_decision',
  'criterion_verdict',
  'secret_release',
  'halt',
  'user_action',
]);

export const ExecutionLogEntrySchema = z.object({
  id: IdSchema,
  request_id: IdSchema.nullable(),
  project_id: IdSchema.nullable(),
  task_id: IdSchema.nullable(),
  step_id: IdSchema.nullable(),
  kind: ExecutionLogKindSchema,
  actor: NonEmptyStringSchema,
  detail: z.unknown(),
  prompt_version: NonEmptyStringSchema.nullable(),
  model_id: NonEmptyStringSchema.nullable(),
  recorded_at: TimestampSchema,
});

export const TaskRecordSchema = z.object({
  task_id: IdSchema,
  project_id: IdSchema,
  request_ids: z.array(IdSchema),
  engine_ids: z.array(IdSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export type LiveEventType = z.infer<typeof LiveEventTypeSchema>;
export type LiveEvent = z.infer<typeof LiveEventSchema>;
export type MessageRole = z.infer<typeof MessageRoleSchema>;
export type Message = z.infer<typeof MessageSchema>;
export type ExecutionLogKind = z.infer<typeof ExecutionLogKindSchema>;
export type ExecutionLogEntry = z.infer<typeof ExecutionLogEntrySchema>;
export type TaskRecord = z.infer<typeof TaskRecordSchema>;

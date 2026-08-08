import { z } from 'zod';
import {
  IdSchema,
  NonEmptyStringSchema,
  TimestampSchema,
} from './primitives.js';

export const IntentSchema = z.enum([
  'chat',
  'dev_task',
  'automation_task',
  'script_task',
  'account_action',
]);

export const DownstreamServiceSchema = z.enum([
  'task-runner',
  'automation',
  'dev-env',
  'engine-session',
]);

export const FailurePolicySchema = z.enum([
  'abort',
  'retry',
  'replan',
  'continue',
]);

export const StepStateSchema = z.enum([
  'pending',
  'awaiting_confirmation',
  'running',
  'succeeded',
  'failed',
  'aborted',
  'never_attempted',
]);

export const ActionStepSchema = z.object({
  step_id: IdSchema,
  position: z.number().int().nonnegative(),
  description: NonEmptyStringSchema.max(500),
  service: DownstreamServiceSchema,
  requires_confirmation: z.boolean(),
  confirmation_reason: z.string().nullable(),
  on_failure: FailurePolicySchema,
  reversible: z.boolean(),
  criterion_refs: z.array(IdSchema),
  state: StepStateSchema,
});

export const ActionPlanSchema = z.object({
  id: IdSchema,
  request_id: IdSchema,
  project_id: IdSchema,
  task_id: IdSchema,
  intent: IntentSchema,
  target_engine_id: IdSchema.nullable(),
  target_model_id: NonEmptyStringSchema.nullable(),
  steps: z.array(ActionStepSchema),
  prompt_version: NonEmptyStringSchema,
  created_at: TimestampSchema,
});

export const HaltReasonSchema = z.enum([
  'kill_switch',
  'step_failure',
  'project_switch',
  'user_stop',
]);

export const HaltSignalSchema = z.object({
  id: IdSchema,
  request_id: IdSchema.nullable(),
  project_id: IdSchema.nullable(),
  reason: HaltReasonSchema,
  issued_at: TimestampSchema,
});

export const StepOutcomeSchema = z.object({
  step_id: IdSchema,
  state: StepStateSchema,
  touched_paths: z.array(z.string()),
  exit_code: z.number().int().nullable(),
  error_message: z.string().nullable(),
  started_at: TimestampSchema.nullable(),
  ended_at: TimestampSchema.nullable(),
});

export const ReconciliationRecordSchema = z.object({
  id: IdSchema,
  request_id: IdSchema,
  task_id: IdSchema,
  halt_reason: HaltReasonSchema,
  steps_total: z.number().int().nonnegative(),
  steps_completed: z.number().int().nonnegative(),
  step_outcomes: z.array(StepOutcomeSchema),
  criteria_verified_ids: z.array(IdSchema),
  criteria_unverified_ids: z.array(IdSchema),
  plain_summary: NonEmptyStringSchema.max(1000),
  written_at: TimestampSchema,
});

export type Intent = z.infer<typeof IntentSchema>;
export type DownstreamService = z.infer<typeof DownstreamServiceSchema>;
export type FailurePolicy = z.infer<typeof FailurePolicySchema>;
export type StepState = z.infer<typeof StepStateSchema>;
export type ActionStep = z.infer<typeof ActionStepSchema>;
export type ActionPlan = z.infer<typeof ActionPlanSchema>;
export type HaltReason = z.infer<typeof HaltReasonSchema>;
export type HaltSignal = z.infer<typeof HaltSignalSchema>;
export type StepOutcome = z.infer<typeof StepOutcomeSchema>;
export type ReconciliationRecord = z.infer<typeof ReconciliationRecordSchema>;

import { z } from 'zod';
import {
  IdSchema,
  NonEmptyStringSchema,
  PercentageSchema,
  TimestampSchema,
  WeightSchema,
} from './primitives.js';

export const TaskStateSchema = z.enum([
  'pending',
  'ready',
  'in_progress',
  'blocked',
  'awaiting_confirmation',
  'awaiting_clarification',
  'verifying',
  'done',
  'failed',
  'skipped',
  'ignored',
]);

export const TaskOriginSchema = z.enum(['analyst', 'engine', 'mediator', 'user']);

export const TaskKindSchema = z.enum([
  'code',
  'automation',
  'research',
  'real_world',
  'setup',
  'verification',
]);

export const AssignedRoleSchema = z.enum(['engine', 'mediator', 'user']);

export const CheckKindSchema = z.enum(['deterministic', 'inspected']);

export const CriterionStatusSchema = z.enum([
  'unverified',
  'verified',
  'failed',
  'ignored',
]);

export const CheckTypeSchema = z.enum([
  'file_exists',
  'file_hash',
  'port_open',
  'http_status',
  'sql_result',
  'process_exit',
  'window_title',
  'text_on_screen',
]);

export const CheckSpecSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('file_exists'),
    path: NonEmptyStringSchema,
  }),
  z.object({
    type: z.literal('file_hash'),
    path: NonEmptyStringSchema,
    expected_sha256: NonEmptyStringSchema,
  }),
  z.object({
    type: z.literal('port_open'),
    host: NonEmptyStringSchema,
    port: z.number().int().min(1).max(65535),
  }),
  z.object({
    type: z.literal('http_status'),
    url: NonEmptyStringSchema,
    expected_status: z.number().int().min(100).max(599),
    timeout_ms: z.number().int().positive(),
  }),
  z.object({
    type: z.literal('sql_result'),
    connection_ref: NonEmptyStringSchema,
    query: NonEmptyStringSchema,
    expect: NonEmptyStringSchema,
  }),
  z.object({
    type: z.literal('process_exit'),
    step_id: IdSchema,
    expected_code: z.number().int(),
  }),
  z.object({
    type: z.literal('window_title'),
    pattern: NonEmptyStringSchema,
  }),
  z.object({
    type: z.literal('text_on_screen'),
    text: NonEmptyStringSchema,
    region: z
      .object({
        x: z.number().int().nonnegative(),
        y: z.number().int().nonnegative(),
        width: z.number().int().positive(),
        height: z.number().int().positive(),
      })
      .nullable(),
  }),
]);

export const AcceptanceCriterionSchema = z.object({
  id: IdSchema,
  task_id: IdSchema,
  statement: NonEmptyStringSchema.max(500),
  check_kind: CheckKindSchema,
  check_spec: CheckSpecSchema.nullable(),
  weight: WeightSchema,
  status: CriterionStatusSchema,
  status_reason: z.string().nullable(),
  evidence_ids: z.array(IdSchema),
  verified_at: TimestampSchema.nullable(),
  verified_by: z.string().nullable(),
});

export const TaskNodeSchema = z.object({
  id: IdSchema,
  project_id: IdSchema,
  parent_id: IdSchema.nullable(),
  title: NonEmptyStringSchema.max(200),
  description: z.string(),
  origin: TaskOriginSchema,
  kind: TaskKindSchema,
  state: TaskStateSchema,
  state_reason: z.string().nullable(),
  depends_on: z.array(IdSchema),
  assigned_role: AssignedRoleSchema,
  action_plan_id: IdSchema.nullable(),
  position: z.number().int().nonnegative(),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export const TaskTreeSchema = z.object({
  project_id: IdSchema,
  nodes: z.array(TaskNodeSchema),
  criteria: z.array(AcceptanceCriterionSchema),
  built_at: TimestampSchema,
  built_by_prompt_version: NonEmptyStringSchema,
});

export const TaskProgressSchema = z.object({
  task_id: IdSchema,
  percentage: PercentageSchema,
  verified_weight: z.number().nonnegative(),
  counted_weight: z.number().nonnegative(),
  criteria_total: z.number().int().nonnegative(),
  criteria_verified: z.number().int().nonnegative(),
  criteria_failed: z.number().int().nonnegative(),
  criteria_ignored: z.number().int().nonnegative(),
});

export const ProgressSnapshotSchema = z.object({
  project_id: IdSchema,
  computed_at: TimestampSchema,
  overall: TaskProgressSchema,
  per_task: z.array(TaskProgressSchema),
});

export type TaskState = z.infer<typeof TaskStateSchema>;
export type TaskOrigin = z.infer<typeof TaskOriginSchema>;
export type TaskKind = z.infer<typeof TaskKindSchema>;
export type CheckKind = z.infer<typeof CheckKindSchema>;
export type CriterionStatus = z.infer<typeof CriterionStatusSchema>;
export type CheckSpec = z.infer<typeof CheckSpecSchema>;
export type AcceptanceCriterion = z.infer<typeof AcceptanceCriterionSchema>;
export type TaskNode = z.infer<typeof TaskNodeSchema>;
export type TaskTree = z.infer<typeof TaskTreeSchema>;
export type TaskProgress = z.infer<typeof TaskProgressSchema>;
export type ProgressSnapshot = z.infer<typeof ProgressSnapshotSchema>;

export type CheckType = z.infer<typeof CheckTypeSchema>;
export type AssignedRole = z.infer<typeof AssignedRoleSchema>;

const _checkTypeCoverage: Record<CheckType, true> = CheckSpecSchema.options.reduce(
  (acc, option) => ({ ...acc, [option.shape.type.value]: true }),
  {} as Record<CheckType, true>,
);

void _checkTypeCoverage;

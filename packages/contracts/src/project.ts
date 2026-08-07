import { z } from 'zod';
import {
  ConfidenceSchema,
  HashSchema,
  IdSchema,
  NonEmptyStringSchema,
  TimestampSchema,
  UrlSchema,
} from './primitives.js';

export const ProjectStateSchema = z.enum([
  'draft',
  'active',
  'paused',
  'archived',
]);

export const ProjectTypeSchema = z.enum([
  'code',
  'automation',
  'research',
  'real_world',
  'mixed',
]);

export const SensitivityFlagSchema = z.enum([
  'credentialed',
  'destructive',
  'financial',
  'public_facing',
]);

export const ProjectSchema = z.object({
  id: IdSchema,
  name: NonEmptyStringSchema.max(120),
  goal: NonEmptyStringSchema.max(500),
  project_type: ProjectTypeSchema,
  state: ProjectStateSchema,
  description: z.string().nullable(),
  target_environment: z.string().nullable(),
  constraints: z.array(z.string()),
  do_not_touch: z.array(z.string()),
  sensitivity_flags: z.array(SensitivityFlagSchema),
  success_criteria: z.array(z.string()),
  referenced_project_ids: z.array(IdSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
  archived_at: TimestampSchema.nullable(),
});

export const MaterialKindSchema = z.enum(['folder', 'file', 'image', 'link']);

export const ProjectMaterialSchema = z.object({
  id: IdSchema,
  project_id: IdSchema,
  kind: MaterialKindSchema,
  path: z.string().nullable(),
  url: UrlSchema.nullable(),
  caption: z.string().nullable(),
  note: z.string().nullable(),
  size_bytes: z.number().int().nonnegative().nullable(),
  content_hash: HashSchema.nullable(),
  created_at: TimestampSchema,
});

export const LanguageCountSchema = z.object({
  language: NonEmptyStringSchema,
  file_count: z.number().int().nonnegative(),
});

export const DependencyManifestSchema = z.object({
  path: NonEmptyStringSchema,
  ecosystem: NonEmptyStringSchema,
  dependency_count: z.number().int().nonnegative(),
});

export const SecretFindingSchema = z.object({
  path: NonEmptyStringSchema,
  line: z.number().int().positive(),
  rule: NonEmptyStringSchema,
  confidence: ConfidenceSchema,
});

export const UploadScanSchema = z.object({
  id: IdSchema,
  project_id: IdSchema,
  material_id: IdSchema,
  total_files: z.number().int().nonnegative(),
  total_size_bytes: z.number().int().nonnegative(),
  file_tree: z.array(z.string()),
  languages: z.array(LanguageCountSchema),
  dependency_manifests: z.array(DependencyManifestSchema),
  entry_points: z.array(z.string()),
  secret_findings: z.array(SecretFindingSchema),
  scanned_at: TimestampSchema,
});

export const ConceiveBlockKindSchema = z.enum([
  'markdown',
  'image',
  'link',
  'project_ref',
  'file_ref',
]);

export const ConceiveBlockSchema = z.object({
  id: IdSchema,
  kind: ConceiveBlockKindSchema,
  position: z.number().int().nonnegative(),
  content: z.string().nullable(),
  caption: z.string().nullable(),
  note: z.string().nullable(),
  url: UrlSchema.nullable(),
  ref_project_id: IdSchema.nullable(),
  ref_material_id: IdSchema.nullable(),
});

export const ConceiveRevisionSchema = z.object({
  id: IdSchema,
  conceive_id: IdSchema,
  revision_number: z.number().int().positive(),
  blocks: z.array(ConceiveBlockSchema),
  created_at: TimestampSchema,
});

export const ConceiveSchema = z.object({
  id: IdSchema,
  project_id: IdSchema,
  current_revision_number: z.number().int().nonnegative(),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export type ProjectState = z.infer<typeof ProjectStateSchema>;
export type ProjectType = z.infer<typeof ProjectTypeSchema>;
export type Project = z.infer<typeof ProjectSchema>;
export type ProjectMaterial = z.infer<typeof ProjectMaterialSchema>;
export type UploadScan = z.infer<typeof UploadScanSchema>;
export type SecretFinding = z.infer<typeof SecretFindingSchema>;
export type ConceiveBlock = z.infer<typeof ConceiveBlockSchema>;
export type ConceiveRevision = z.infer<typeof ConceiveRevisionSchema>;
export type Conceive = z.infer<typeof ConceiveSchema>;
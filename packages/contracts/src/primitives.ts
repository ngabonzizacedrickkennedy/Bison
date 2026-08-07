import { z } from 'zod';

export const IdSchema = z.string().uuid();

export const TimestampSchema = z.string().datetime({ offset: true });

export const SlugSchema = z
  .string()
  .min(1)
  .max(64)
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);

export const NonEmptyStringSchema = z.string().min(1);

export const HashSchema = z.string().regex(/^[a-f0-9]{64}$/);

export const UrlSchema = z.string().url();

export const WeightSchema = z.number().int().min(1).max(100);

export const PercentageSchema = z.number().min(0).max(100);

export const ConfidenceSchema = z.number().min(0).max(1);

export type Id = z.infer<typeof IdSchema>;
export type Timestamp = z.infer<typeof TimestampSchema>;
export type Slug = z.infer<typeof SlugSchema>;
export type Hash = z.infer<typeof HashSchema>;
export type Weight = z.infer<typeof WeightSchema>;
export type Percentage = z.infer<typeof PercentageSchema>;
export type Confidence = z.infer<typeof ConfidenceSchema>;
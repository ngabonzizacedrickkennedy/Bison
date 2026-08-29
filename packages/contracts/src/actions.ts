import { z } from "zod";
import { NonEmptyStringSchema } from "./primitives.js";

export const ActionTypeSchema = z.enum([
  "write_file",
  "run_python_script",
  "run_python_module",
  "install_python_packages",
]);

export const ActionSpecSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("write_file"),
    path: NonEmptyStringSchema,
    content: z.string(),
  }),
  z.object({
    type: z.literal("run_python_script"),
    script_path: NonEmptyStringSchema,
    arguments: z.array(z.string()),
  }),
  z.object({
    type: z.literal("run_python_module"),
    module: NonEmptyStringSchema,
    arguments: z.array(z.string()),
  }),
  z.object({
    type: z.literal("install_python_packages"),
    packages: z.array(NonEmptyStringSchema).min(1),
  }),
]);

export type ActionType = z.infer<typeof ActionTypeSchema>;
export type ActionSpec = z.infer<typeof ActionSpecSchema>;

const _actionTypeCoverage: Record<ActionType, true> = ActionSpecSchema.options.reduce(
  (acc, option) => ({ ...acc, [option.shape.type.value]: true }),
  {} as Record<ActionType, true>,
);

void _actionTypeCoverage;

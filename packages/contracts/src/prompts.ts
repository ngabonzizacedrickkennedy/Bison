import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const PROMPT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..", "prompts");

export const PromptNameSchema = z.string().regex(/^[a-z][a-z0-9]*$/);

export const PromptVersionSchema = z.object({
  name: PromptNameSchema,
  version: z.string().regex(/^v\d+$/),
  hash: z.string().regex(/^[a-f0-9]{64}$/),
  text: z.string().min(1),
});

export type PromptName = z.infer<typeof PromptNameSchema>;
export type PromptVersion = z.infer<typeof PromptVersionSchema>;

const CURRENT_VERSION = "v1";

const cache = new Map<string, PromptVersion>();

export function loadPrompt(name: string, version: string = CURRENT_VERSION): PromptVersion {
  const key = `${name}.${version}`;
  const cached = cache.get(key);
  if (cached) return cached;

  const text = readFileSync(resolve(PROMPT_DIR, `${key}.md`), "utf8");
  const hash = createHash("sha256").update(text, "utf8").digest("hex");

  const loaded = PromptVersionSchema.parse({ name, version, hash, text });
  cache.set(key, loaded);
  return loaded;
}

export function promptRef(name: string, version: string = CURRENT_VERSION): string {
  return `${name}.${version}.${loadPrompt(name, version).hash.slice(0, 12)}`;
}

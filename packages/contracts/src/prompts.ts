import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import { ModelRoleSchema } from './models.js';

const PROMPT_DIR = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  'prompts',
);

export const PromptVersionSchema = z.object({
  role: ModelRoleSchema,
  version: z.string().regex(/^v\d+$/),
  hash: z.string().regex(/^[a-f0-9]{64}$/),
  text: z.string().min(1),
});

export type PromptVersion = z.infer<typeof PromptVersionSchema>;

const CURRENT_VERSION = 'v1';

const cache = new Map<string, PromptVersion>();

export function loadPrompt(
  role: z.infer<typeof ModelRoleSchema>,
  version: string = CURRENT_VERSION,
): PromptVersion {
  const key = `${role}.${version}`;
  const cached = cache.get(key);
  if (cached) return cached;

  const text = readFileSync(resolve(PROMPT_DIR, `${key}.md`), 'utf8');
  const hash = createHash('sha256').update(text, 'utf8').digest('hex');

  const loaded = PromptVersionSchema.parse({ role, version, hash, text });
  cache.set(key, loaded);
  return loaded;
}

export function promptRef(
  role: z.infer<typeof ModelRoleSchema>,
  version: string = CURRENT_VERSION,
): string {
  return `${role}.${version}.${loadPrompt(role, version).hash.slice(0, 12)}`;
}

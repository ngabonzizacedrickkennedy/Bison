import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promptRef } from "../src/prompts.js";

const LOCK_PATH = resolve(dirname(fileURLToPath(import.meta.url)), "..", "prompts", "hashes.json");

const lock: Record<string, string> = JSON.parse(readFileSync(LOCK_PATH, "utf8"));

const drift: string[] = [];
const missing: string[] = [];

for (const [key, expected] of Object.entries(lock)) {
  const [name, version] = key.split(".");
  if (!name || !version) {
    missing.push(`${key} is not in the form name.version`);
    continue;
  }

  let actual: string;
  try {
    actual = promptRef(name, version).split(".")[2] ?? "";
  } catch (error) {
    missing.push(`${key}: ${error instanceof Error ? error.message : String(error)}`);
    continue;
  }

  if (actual !== expected) {
    drift.push(`${key}  expected ${expected}  actual ${actual}`);
  }
}

if (missing.length > 0 || drift.length > 0) {
  for (const line of missing) process.stderr.write(`missing  ${line}\n`);
  for (const line of drift) process.stderr.write(`drift    ${line}\n`);
  process.stderr.write(
    "\nPrompt content changed without a version bump.\n" +
      "Either revert the edit, or create the next version and add it to prompts/hashes.json.\n",
  );
  process.exit(1);
}

process.stdout.write(`${Object.keys(lock).length} prompt hashes match the lock\n`);

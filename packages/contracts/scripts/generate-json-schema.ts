import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";
import * as contracts from "../src/index.js";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "..", "generated");
const outFile = resolve(outDir, "bison-contracts.schema.json");

const definitions: Record<string, unknown> = {};

for (const [exportName, value] of Object.entries(contracts)) {
  if (!(value instanceof z.ZodType)) continue;
  if (!exportName.endsWith("Schema")) continue;

  const name = exportName.slice(0, -"Schema".length);

  // Passing `name` makes zodToJsonSchema return a document shaped as
  // { $ref: '#/definitions/<name>', definitions: { <name>: schema } }.
  // Nesting that whole document under our own definitions[name] would make the
  // $ref resolve back to the wrapper instead of the schema, so unwrap it here.
  const generated = zodToJsonSchema(value, {
    name,
    target: "jsonSchema7",
    $refStrategy: "none",
    errorMessages: false,
  }) as { definitions?: Record<string, unknown> };

  const bare = generated.definitions?.[name];

  if (!bare) {
    throw new Error(`Failed to unwrap generated schema for ${exportName}`);
  }

  definitions[name] = bare;
}

const names = Object.keys(definitions).sort();

if (names.length === 0) {
  throw new Error("No schemas discovered in contracts index");
}

const document = {
  $schema: "http://json-schema.org/draft-07/schema#",
  title: "BISON Contracts",
  description: "Generated from packages/contracts/src. Do not edit by hand.",
  definitions: Object.fromEntries(names.map((n) => [n, definitions[n]])),
};

mkdirSync(outDir, { recursive: true });
writeFileSync(outFile, `${JSON.stringify(document, null, 2)}\n`, "utf8");

process.stdout.write(`${names.length} schemas written to ${outFile}\n`);

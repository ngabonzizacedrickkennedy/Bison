import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

function defaultDataDir(): string {
  const localAppData = process.env.LOCALAPPDATA;

  if (localAppData !== undefined && localAppData !== "") {
    return join(localAppData, "BISON");
  }

  return join(homedir(), ".bison");
}

export function resolveDataDir(): string {
  const override = process.env.BISON_DATA_DIR;
  const dir = override === undefined || override === "" ? defaultDataDir() : resolve(override);

  mkdirSync(dir, { recursive: true });

  return dir;
}

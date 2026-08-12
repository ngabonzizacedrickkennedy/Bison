import { createCipheriv, createDecipheriv, randomBytes, randomUUID, scryptSync } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { SecretsBackend } from "@bison/contracts";
import { probeCapability, type Capability } from "../capability.js";
import { config } from "../config.js";

const SALT_BYTES = 16;
const IV_BYTES = 12;
const TAG_BYTES = 16;
const KEY_BYTES = 32;

const PROBE_SERVICE = "bison-capability-probe";

interface KeytarModule {
  setPassword: (service: string, account: string, password: string) => Promise<void>;
  getPassword: (service: string, account: string) => Promise<string | null>;
  deletePassword: (service: string, account: string) => Promise<boolean>;
}

function keytarSpecifier(): string {
  return "keytar";
}

function asKeytarModule(loaded: unknown): KeytarModule | undefined {
  const candidate = (loaded as { default?: unknown }).default ?? loaded;
  const shape = candidate as Partial<KeytarModule>;

  if (
    typeof shape.setPassword !== "function" ||
    typeof shape.getPassword !== "function" ||
    typeof shape.deletePassword !== "function"
  ) {
    return undefined;
  }

  return shape as KeytarModule;
}

async function keytarStoresSecret(): Promise<boolean> {
  try {
    const keytar = asKeytarModule(await import(keytarSpecifier()));

    if (keytar === undefined) return false;

    const account = randomUUID();
    const secret = randomBytes(24).toString("hex");

    await keytar.setPassword(PROBE_SERVICE, account, secret);
    const recovered = await keytar.getPassword(PROBE_SERVICE, account);
    await keytar.deletePassword(PROBE_SERVICE, account);

    return recovered === secret;
  } catch {
    return false;
  }
}

async function encryptedFileRoundTrips(): Promise<boolean> {
  const directory = await mkdtemp(join(config.dataDir, "probe-secrets-"));
  const file = join(directory, "probe.age");

  try {
    const secret = randomBytes(24).toString("hex");
    const salt = randomBytes(SALT_BYTES);
    const iv = randomBytes(IV_BYTES);
    const key = scryptSync(PROBE_SERVICE, salt, KEY_BYTES);

    const cipher = createCipheriv("aes-256-gcm", key, iv);
    const sealed = Buffer.concat([cipher.update(secret, "utf8"), cipher.final()]);

    await writeFile(file, Buffer.concat([salt, iv, cipher.getAuthTag(), sealed]));

    const stored = await readFile(file);
    const storedSalt = stored.subarray(0, SALT_BYTES);
    const storedIv = stored.subarray(SALT_BYTES, SALT_BYTES + IV_BYTES);
    const storedTag = stored.subarray(SALT_BYTES + IV_BYTES, SALT_BYTES + IV_BYTES + TAG_BYTES);
    const storedBody = stored.subarray(SALT_BYTES + IV_BYTES + TAG_BYTES);

    const decipher = createDecipheriv(
      "aes-256-gcm",
      scryptSync(PROBE_SERVICE, storedSalt, KEY_BYTES),
      storedIv,
    );
    decipher.setAuthTag(storedTag);

    const opened = Buffer.concat([decipher.update(storedBody), decipher.final()]).toString("utf8");

    return opened === secret;
  } catch {
    return false;
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

export async function probeSecrets(): Promise<Capability<SecretsBackend>> {
  return probeCapability<SecretsBackend>([
    { backend: "keytar", strength: "full", works: keytarStoresSecret },
    { backend: "age_file", strength: "medium", works: encryptedFileRoundTrips },
  ]);
}

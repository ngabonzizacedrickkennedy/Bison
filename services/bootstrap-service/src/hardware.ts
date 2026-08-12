import { statfs } from "node:fs/promises";
import { cpus, release, totalmem, version } from "node:os";
import { HardwareProfileSchema, type HardwareProfile } from "@bison/contracts";
import { config } from "./config.js";

export const MINIMUM_RAM_GB = 16;

const BYTES_PER_GB = 1024 ** 3;

function round(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

async function freeDiskGb(path: string): Promise<number> {
  const stats = await statfs(path);
  return round((stats.bsize * stats.bavail) / BYTES_PER_GB, 1);
}

export async function probeHardware(): Promise<HardwareProfile> {
  return HardwareProfileSchema.parse({
    ram_gb: round(totalmem() / BYTES_PER_GB, 1),
    free_disk_gb: await freeDiskGb(config.dataDir),
    cpu_cores: cpus().length,
    os_version: `${version()} (${release()})`,
  });
}

export function meetsMinimumRam(profile: HardwareProfile): boolean {
  return Math.round(profile.ram_gb) >= MINIMUM_RAM_GB;
}

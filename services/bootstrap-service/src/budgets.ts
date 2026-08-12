import { BudgetsSchema, type Budgets, type HardwareProfile } from "@bison/contracts";

export const LOCAL_MODEL_DISK_FRACTION = 0.25;
export const LOCAL_MODEL_GB_CEILING = 40;
export const MAX_PROJECTS = 10;

export function deriveBudgets(hardware: HardwareProfile): Budgets {
  const fromDisk = hardware.free_disk_gb * LOCAL_MODEL_DISK_FRACTION;
  const allowance = Math.min(fromDisk, LOCAL_MODEL_GB_CEILING);

  return BudgetsSchema.parse({
    local_model_gb: Math.round(allowance * 10) / 10,
    max_projects: MAX_PROJECTS,
  });
}

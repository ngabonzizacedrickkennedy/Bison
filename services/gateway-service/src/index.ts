import { LiveEventSchema, promptRef, type LiveEvent } from "@bison/contracts";

export const SERVICE_NAME = "gateway-service";

export function parseLiveEvent(input: unknown): LiveEvent {
  return LiveEventSchema.parse(input);
}

export function analystPromptRef(): string {
  return promptRef("analyst");
}

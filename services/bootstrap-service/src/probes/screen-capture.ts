import type { ScreenCaptureBackend } from "@bison/contracts";
import { probeCapability, type Capability } from "../capability.js";
import { runPythonProbes } from "./python-probes.js";

export async function probeScreenCapture(): Promise<Capability<ScreenCaptureBackend>> {
  const results = await runPythonProbes();

  return probeCapability<ScreenCaptureBackend>([
    { backend: "mss", strength: "full", works: async () => results.screen_capture },
  ]);
}

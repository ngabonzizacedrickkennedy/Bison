import type { InputInjectionBackend } from "@bison/contracts";
import type { Capability } from "../capability.js";
import { runPythonProbes } from "./python-probes.js";

export async function probeInputInjection(): Promise<Capability<InputInjectionBackend>> {
  const results = await runPythonProbes();

  if (!results.input_injection_available) {
    return { backend: null, strength: "unavailable", available: [] };
  }

  return {
    backend: "pyautogui",
    strength: results.input_injection_verified ? "verified" : "unverified",
    available: ["pyautogui"],
  };
}

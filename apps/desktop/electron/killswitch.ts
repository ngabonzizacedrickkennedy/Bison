import { globalShortcut } from "electron";
import { gatewayHttpUrl } from "./config";

const ACCELERATOR = process.env.BISON_HALT_HOTKEY ?? "Control+Shift+Escape";

const FALLBACK_ACCELERATORS = ["Control+Alt+Shift+H", "Control+Shift+F12"];

const HALT_TIMEOUT_MS = 4000;

export interface HotkeyRegistration {
  accelerator: string | null;
  attempted: string[];
}

export interface HaltDispatch {
  ok: boolean;
  status: number | null;
  detail: string | null;
  acknowledged: number | null;
  silent: number | null;
}

export async function fire(reason = "kill_switch"): Promise<HaltDispatch> {
  try {
    const response = await fetch(`${gatewayHttpUrl}/halt`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reason }),
      signal: AbortSignal.timeout(HALT_TIMEOUT_MS),
    });

    if (!response.ok) {
      return {
        ok: false,
        status: response.status,
        detail: `gateway responded ${response.status}`,
        acknowledged: null,
        silent: null,
      };
    }

    const signal = (await response.json()) as {
      acknowledged_count?: number;
      silent_count?: number;
    };

    return {
      ok: true,
      status: response.status,
      detail: null,
      acknowledged: signal.acknowledged_count ?? null,
      silent: signal.silent_count ?? null,
    };
  } catch (error) {
    return {
      ok: false,
      status: null,
      detail: error instanceof Error ? error.message : String(error),
      acknowledged: null,
      silent: null,
    };
  }
}

export function register(onFired: (result: HaltDispatch) => void): HotkeyRegistration {
  const attempted: string[] = [];

  for (const accelerator of [ACCELERATOR, ...FALLBACK_ACCELERATORS]) {
    attempted.push(accelerator);

    const bound = globalShortcut.register(accelerator, () => {
      void fire().then(onFired);
    });

    if (bound && globalShortcut.isRegistered(accelerator)) {
      return { accelerator, attempted };
    }
  }

  return { accelerator: null, attempted };
}

export function unregister(): void {
  globalShortcut.unregisterAll();
}

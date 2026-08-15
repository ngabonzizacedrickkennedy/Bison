import { useCallback, useEffect, useState } from "react";
import { bindRole, fetchBindings, fetchInstalled, type Role, type RoleBinding } from "./broker";

export type BindingsState = "loading" | "ready" | "failed";

export interface BindingsView {
  bindingsState: BindingsState;
  bindings: RoleBinding[];
  installed: Set<string>;
  rebind: (role: Role, modelId: string) => Promise<void>;
  refreshInstalled: () => Promise<void>;
}

export function useBindings(httpUrl: string): BindingsView {
  const [bindingsState, setBindingsState] = useState<BindingsState>("loading");
  const [bindings, setBindings] = useState<RoleBinding[]>([]);
  const [installed, setInstalled] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;

    Promise.all([fetchBindings(httpUrl), fetchInstalled(httpUrl)])
      .then(([loadedBindings, loadedInstalled]) => {
        if (cancelled) {
          return;
        }
        setBindings(loadedBindings);
        setInstalled(loadedInstalled);
        setBindingsState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setBindingsState("failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [httpUrl]);

  const rebind = useCallback(
    async (role: Role, modelId: string) => {
      const bound = await bindRole(httpUrl, role, modelId);

      setBindings((current) => {
        const others = current.filter((binding) => binding.role !== bound.role);
        return [...others, bound];
      });
    },
    [httpUrl],
  );

  const refreshInstalled = useCallback(async () => {
    setInstalled(await fetchInstalled(httpUrl));
  }, [httpUrl]);

  return { bindingsState, bindings, installed, rebind, refreshInstalled };
}

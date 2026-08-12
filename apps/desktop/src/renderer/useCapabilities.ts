import { useEffect, useState } from "react";
import { fetchManifest, type CapabilityManifest } from "./capabilities";

export type ManifestState = "loading" | "ready" | "failed";

export interface CapabilitiesView {
  manifestState: ManifestState;
  manifest: CapabilityManifest | null;
}

export function useCapabilities(httpUrl: string): CapabilitiesView {
  const [manifestState, setManifestState] = useState<ManifestState>("loading");
  const [manifest, setManifest] = useState<CapabilityManifest | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchManifest(httpUrl)
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setManifest(loaded);
        setManifestState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setManifestState("failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [httpUrl]);

  return { manifestState, manifest };
}

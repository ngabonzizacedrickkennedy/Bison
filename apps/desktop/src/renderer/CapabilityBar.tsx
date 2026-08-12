import { CAPABILITY_NAMES, isDegraded, type CapabilityManifest } from "./capabilities";
import type { ManifestState } from "./useCapabilities";

interface CapabilityBarProps {
  manifestState: ManifestState;
  manifest: CapabilityManifest | null;
}

export function CapabilityBar({ manifestState, manifest }: CapabilityBarProps) {
  if (manifestState === "loading") {
    return <div className="capabilities">detecting machine capabilities</div>;
  }

  if (manifestState === "failed" || manifest === null) {
    return (
      <div className="capabilities">
        capability manifest unavailable — bootstrap-service is not running
      </div>
    );
  }

  return (
    <div className="capabilities">
      {CAPABILITY_NAMES.map((name) => {
        const capability = manifest[name];
        const unavailable = capability.backend === null;

        return (
          <span
            className={`capability ${unavailable ? "off" : isDegraded(capability) ? "degraded" : "on"}`}
            key={name}
            title={`${capability.strength}${capability.available.length > 1 ? ` · fallbacks: ${capability.available.slice(1).join(", ")}` : ""}`}
          >
            <span className="name">{name.replace("_", " ")}</span>
            <span className="backend">{capability.backend ?? "unavailable"}</span>
          </span>
        );
      })}
      <span className="budget">
        {manifest.budgets.local_model_gb} GB models · {manifest.budgets.max_projects} projects
      </span>
    </div>
  );
}

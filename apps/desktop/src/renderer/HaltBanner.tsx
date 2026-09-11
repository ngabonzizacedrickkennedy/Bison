import {
  describeReach,
  firstHaltReason,
  haltedServices,
  silentServices,
  type HaltReason,
} from "./halt";
import type { HaltView } from "./useGateway";

interface HaltBannerProps {
  halt: HaltView;
}

const REASON_LABEL: Record<HaltReason, string> = {
  kill_switch: "the kill switch fired",
  step_failure: "a step failed",
  project_switch: "a project switch",
  user_stop: "you stopped it",
};

export function HaltBanner({ halt }: HaltBannerProps) {
  const { report, signal, halted, pending } = halt;
  const reason = signal?.reason ?? (report === null ? null : firstHaltReason(report));
  const stopped = report === null ? [] : haltedServices(report);
  const silent = report === null ? [] : silentServices(report);

  return (
    <div className={`halt ${halted ? "halted" : "clear"}`}>
      <div className="halt-head">
        <span className="halt-label">{halted ? "halted" : "running"}</span>

        <span className="halt-reason">
          {!halted
            ? "nothing is halted"
            : reason === null
              ? "halted for an unreported reason"
              : REASON_LABEL[reason]}
        </span>

        {halted && signal !== null && (
          <span className="halt-issued">{new Date(signal.issued_at).toLocaleTimeString()}</span>
        )}

        <span className="halt-reach">
          {report === null ? "checking services" : describeReach(report)}
        </span>

        {halted ? (
          <button type="button" className="halt-resume" disabled={pending} onClick={halt.resume}>
            Resume
          </button>
        ) : (
          <button type="button" className="halt-stop" disabled={pending} onClick={halt.stop}>
            Stop
          </button>
        )}
      </div>

      {stopped.length > 0 && <div className="halt-services">stopped: {stopped.join(", ")}</div>}

      {silent.length > 0 && (
        <div className="halt-silent">
          <span>no answer from {silent.join(", ")}</span>
          <button type="button" className="halt-recheck" disabled={pending} onClick={halt.refresh}>
            Recheck
          </button>
        </div>
      )}

      {halt.error !== null && <div className="halt-error">{halt.error}</div>}
    </div>
  );
}

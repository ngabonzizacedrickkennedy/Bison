import { useEffect, useRef } from "react";
import type { RunPhase, RunState } from "./useRun";

interface RunPanelProps {
  run: RunState;
  onStart: () => void;
  onConfirm: (stepId: string) => void;
}

const PHASE_LABEL: Record<RunPhase, string> = {
  idle: "not started",
  starting: "opening the stream",
  running: "running",
  awaiting: "waiting for you",
  finished: "finished",
  halted: "halted",
};

export function RunPanel({ run, onStart, onConfirm }: RunPanelProps) {
  const tailRef = useRef<HTMLDivElement>(null);
  const busy = run.phase === "starting" || run.phase === "running";
  const awaiting = run.awaiting;

  useEffect(() => {
    tailRef.current?.scrollIntoView({ block: "end" });
  }, [run.lines]);

  return (
    <div className={`run ${run.phase}${run.failed ? " errored" : ""}`}>
      <div className="run-head">
        <span className="run-title">orchestration</span>
        <span className="run-phase">{PHASE_LABEL[run.phase]}</span>
        <span className="run-counts">
          {run.tasksTotal === 0
            ? "no run yet"
            : `${run.tasksCompleted} done, ${run.tasksFailed} failed, ${run.tasksTotal} total`}
        </span>
        <span className="run-percentage">
          {run.percentage === null ? "—" : `${run.percentage}%`}
        </span>
        <button type="button" className="run-start" disabled={busy} onClick={onStart}>
          {run.phase === "idle" ? "Run" : "Run again"}
        </button>
      </div>

      {run.task !== null && (
        <div className="run-current">
          <span className="run-task">{run.task.title}</span>
          <span className="run-step">
            {run.step === null
              ? "planning"
              : run.stepsTotal === null
                ? run.step.description
                : `step ${run.step.position + 1} of ${run.stepsTotal} — ${run.step.description}`}
          </span>
        </div>
      )}

      {awaiting !== null && (
        <div className="run-gate">
          <div className="run-gate-body">
            <span className="run-gate-label">this step needs your approval</span>
            <span className="run-gate-action">{awaiting.description}</span>
            {awaiting.reason !== null && <span className="run-gate-reason">{awaiting.reason}</span>}
          </div>
          <button
            type="button"
            className="run-continue"
            disabled={busy}
            onClick={() => {
              onConfirm(awaiting.step_id);
            }}
          >
            Continue
          </button>
        </div>
      )}

      {run.lines.length > 0 && (
        <div className="run-output">
          {run.lines.map((line) => (
            <div
              className={`run-line ${line.stream}`}
              key={`${line.step_id}:${line.stream}:${line.step_sequence}`}
            >
              {line.text}
            </div>
          ))}
          <div ref={tailRef} />
        </div>
      )}

      {run.detail !== null && <div className="run-detail">{run.detail}</div>}
    </div>
  );
}

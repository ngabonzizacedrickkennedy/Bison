import { useCallback, useEffect, useReducer, useRef } from "react";
import { openConfirm, openRun, type RunEvent, type RunStream } from "./runstream";

const OUTPUT_LIMIT = 500;

export type RunPhase = "idle" | "starting" | "running" | "awaiting" | "finished" | "halted";

export interface RunTask {
  task_id: string;
  title: string;
  position: number;
}

export interface RunStep {
  task_id: string;
  step_id: string;
  position: number;
  description: string;
  reason: string | null;
}

export interface RunLine {
  step_id: string;
  stream: string;
  step_sequence: number;
  text: string;
}

export interface RunState {
  phase: RunPhase;
  requestId: string | null;
  task: RunTask | null;
  step: RunStep | null;
  awaiting: RunStep | null;
  lines: RunLine[];
  tasksTotal: number;
  tasksCompleted: number;
  tasksFailed: number;
  stepsTotal: number | null;
  percentage: number | null;
  detail: string | null;
  failed: boolean;
}

export interface RunView {
  run: RunState;
  start: () => void;
  confirm: (stepId: string) => void;
}

type RunAction =
  | { kind: "opening" }
  | { kind: "opened"; requestId: string }
  | { kind: "event"; event: RunEvent }
  | { kind: "failed"; detail: string };

const IDLE: RunState = {
  phase: "idle",
  requestId: null,
  task: null,
  step: null,
  awaiting: null,
  lines: [],
  tasksTotal: 0,
  tasksCompleted: 0,
  tasksFailed: 0,
  stepsTotal: null,
  percentage: null,
  detail: null,
  failed: false,
};

function appended(lines: RunLine[], line: RunLine): RunLine[] {
  const next = [...lines, line];

  return next.length > OUTPUT_LIMIT ? next.slice(next.length - OUTPUT_LIMIT) : next;
}

function absorb(state: RunState, event: RunEvent): RunState {
  switch (event.event) {
    case "run_started":
      return {
        ...state,
        phase: "running",
        task: null,
        step: null,
        awaiting: null,
        lines: [],
        tasksTotal: event.tasks_total,
        tasksCompleted: 0,
        tasksFailed: 0,
        stepsTotal: null,
        detail: null,
        failed: false,
      };
    case "task_started":
      return {
        ...state,
        phase: "running",
        task: { task_id: event.task_id, title: event.title, position: event.position },
        step: null,
        stepsTotal: null,
      };
    case "plan_ready":
      return { ...state, stepsTotal: event.steps_total };
    case "task_replanning":
      return { ...state, step: null, stepsTotal: null, detail: event.reason };
    case "step_awaiting_confirmation":
      return {
        ...state,
        phase: "awaiting",
        step: null,
        awaiting: {
          task_id: event.task_id,
          step_id: event.step_id,
          position: event.position,
          description: event.description,
          reason: event.reason,
        },
      };
    case "step_started":
      return {
        ...state,
        phase: "running",
        awaiting: null,
        step: {
          task_id: event.task_id,
          step_id: event.step_id,
          position: event.position,
          description: event.description,
          reason: null,
        },
      };
    case "step_output":
      return {
        ...state,
        lines: appended(state.lines, {
          step_id: event.step_id,
          stream: event.stream,
          step_sequence: event.step_sequence,
          text: event.text,
        }),
      };
    case "step_finished":
      return { ...state, step: null, detail: event.error_message ?? state.detail };
    case "criterion_settled":
      return state;
    case "task_finished":
      return {
        ...state,
        task: null,
        step: null,
        percentage: event.project_percentage,
        detail: event.reason ?? state.detail,
      };
    case "halted":
      return { ...state, phase: "halted", step: null, awaiting: null, detail: event.reason };
    case "run_finished":
      return {
        ...state,
        phase: state.phase === "awaiting" ? "awaiting" : "finished",
        task: null,
        step: null,
        tasksCompleted: event.tasks_completed,
        tasksFailed: event.tasks_failed,
        tasksTotal: event.tasks_total,
        percentage: event.project_percentage,
      };
    case "error":
      return { ...state, phase: "finished", step: null, detail: event.detail, failed: true };
  }
}

function reduce(state: RunState, action: RunAction): RunState {
  switch (action.kind) {
    case "opening":
      return { ...IDLE, phase: "starting", percentage: state.percentage };
    case "opened":
      return { ...state, requestId: action.requestId };
    case "event":
      return absorb(state, action.event);
    case "failed":
      return { ...state, phase: "finished", step: null, detail: action.detail, failed: true };
  }
}

export function useRun(httpUrl: string, onSettled: () => void): RunView {
  const [run, dispatch] = useReducer(reduce, IDLE);
  const controllerRef = useRef<AbortController | null>(null);
  const settledRef = useRef(onSettled);

  useEffect(() => {
    settledRef.current = onSettled;
  }, [onSettled]);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, []);

  const consume = useCallback((open: (signal: AbortSignal) => Promise<RunStream>): void => {
    controllerRef.current?.abort();

    const controller = new AbortController();
    controllerRef.current = controller;

    dispatch({ kind: "opening" });

    void (async () => {
      try {
        const stream = await open(controller.signal);

        dispatch({ kind: "opened", requestId: stream.requestId });

        await stream.drain((event) => {
          dispatch({ kind: "event", event });
        });
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }

        dispatch({
          kind: "failed",
          detail: error instanceof Error ? error.message : String(error),
        });
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }

        if (!controller.signal.aborted) {
          settledRef.current();
        }
      }
    })();
  }, []);

  const start = useCallback(() => {
    consume((signal) => openRun(httpUrl, signal));
  }, [consume, httpUrl]);

  const confirm = useCallback(
    (stepId: string) => {
      consume((signal) => openConfirm(httpUrl, stepId, signal));
    },
    [consume, httpUrl],
  );

  return { run, start, confirm };
}

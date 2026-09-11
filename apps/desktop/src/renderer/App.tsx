import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ActivityBar } from "./ActivityBar";
import { AddTask } from "./AddTask";
import { CapabilityBar } from "./CapabilityBar";
import { HaltBanner } from "./HaltBanner";
import { ModelPicker } from "./ModelPicker";
import { RoleBar } from "./RoleBar";
import { RunPanel } from "./RunPanel";
import { TaskList } from "./TaskList";
import type { Role } from "./broker";
import type { TaskDraft } from "./tasks";
import { useBindings } from "./useBindings";
import { useCapabilities } from "./useCapabilities";
import { useGateway } from "./useGateway";
import { useRun } from "./useRun";
import { useTasks } from "./useTasks";
import "./styles.css";

export function App() {
  const { state, historyState, messages, activity, halt, send } = useGateway(
    window.bison.gatewayWebSocketUrl,
    window.bison.gatewayHttpUrl,
  );
  const { manifestState, manifest } = useCapabilities(window.bison.gatewayHttpUrl);
  const { bindingsState, bindings, installed, rebind, refreshInstalled } = useBindings(
    window.bison.gatewayHttpUrl,
  );
  const { tasksState, tasks, progress, refresh, addTask, transition } = useTasks(
    window.bison.gatewayHttpUrl,
  );
  const [draft, setDraft] = useState("");
  const [taskError, setTaskError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [pickerRole, setPickerRole] = useState<Role | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const settle = useCallback(() => {
    void refresh().catch(() => {
      setTaskError("the task tree could not be refreshed");
    });
  }, [refresh]);

  const { run, start, confirm } = useRun(window.bison.gatewayHttpUrl, settle);

  const busy = activity.phase === "invoking";
  const pickerBinding = bindings.find((binding) => binding.role === pickerRole);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  useEffect(() => {
    if (!busy) {
      setElapsedSeconds(0);
      return;
    }

    const startedAt = Date.now();
    setElapsedSeconds(0);

    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [busy]);

  const move = (taskId: string, state: string, reason: string | null) => {
    setTaskError(null);
    transition(taskId, state, reason).catch((error: unknown) => {
      setTaskError(error instanceof Error ? error.message : String(error));
    });
  };

  const add = async (draft: TaskDraft): Promise<boolean> => {
    setTaskError(null);

    try {
      await addTask(draft);

      return true;
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : String(error));

      return false;
    }
  };

  const submit = (submitEvent: FormEvent) => {
    submitEvent.preventDefault();
    const content = draft.trim();
    if (content.length === 0 || busy) {
      return;
    }
    if (send(content)) {
      setDraft("");
    }
  };

  return (
    <div className="shell">
      <div className="status">
        <span className={`indicator ${state}`} />
        <span>{state}</span>
        <span className="detail">
          {historyState === "loading" && "loading history"}
          {historyState === "failed" && "history unavailable"}
          {historyState === "ready" && `${messages.length} messages`}
        </span>
      </div>

      <HaltBanner halt={halt} />

      <CapabilityBar manifestState={manifestState} manifest={manifest} />

      <RoleBar bindingsState={bindingsState} bindings={bindings} onPick={setPickerRole} />

      <TaskList tasksState={tasksState} tasks={tasks} progress={progress} onTransition={move} />

      <AddTask onAdd={add} />

      <RunPanel run={run} onStart={start} onConfirm={confirm} />

      {taskError !== null && <div className="picker-error">{taskError}</div>}

      <div className="stream">
        {messages.map((message) => (
          <div className="message" key={message.id}>
            <div className="meta">
              <span className="role">{message.role}</span>
              <span className="time">{new Date(message.created_at).toLocaleTimeString()}</span>
            </div>
            <div className="content">{message.content}</div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <ActivityBar activity={activity} elapsedSeconds={elapsedSeconds} />

      <form className="composer" onSubmit={submit}>
        <input
          value={draft}
          onChange={(changeEvent) => setDraft(changeEvent.target.value)}
          placeholder={busy ? "waiting for the model" : "Send a message"}
          disabled={busy}
          autoFocus
        />
        <button type="submit" disabled={state !== "open" || busy}>
          Send
        </button>
      </form>

      {pickerRole !== null && (
        <ModelPicker
          httpUrl={window.bison.gatewayHttpUrl}
          role={pickerRole}
          boundModelId={pickerBinding?.model_id ?? null}
          installed={installed}
          onSelect={(modelId) => rebind(pickerRole, modelId)}
          onPulled={refreshInstalled}
          onClose={() => setPickerRole(null)}
        />
      )}
    </div>
  );
}

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ActivityBar } from "./ActivityBar";
import { CapabilityBar } from "./CapabilityBar";
import { ModelPicker } from "./ModelPicker";
import { RoleBar } from "./RoleBar";
import type { Role } from "./broker";
import { useBindings } from "./useBindings";
import { useCapabilities } from "./useCapabilities";
import { useGateway } from "./useGateway";
import "./styles.css";

export function App() {
  const { state, historyState, messages, activity, send } = useGateway(
    window.bison.gatewayWebSocketUrl,
    window.bison.gatewayHttpUrl,
  );
  const { manifestState, manifest } = useCapabilities(window.bison.gatewayHttpUrl);
  const { bindingsState, bindings, installed, rebind, refreshInstalled } = useBindings(
    window.bison.gatewayHttpUrl,
  );
  const [draft, setDraft] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [pickerRole, setPickerRole] = useState<Role | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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

      <CapabilityBar manifestState={manifestState} manifest={manifest} />

      <RoleBar bindingsState={bindingsState} bindings={bindings} onPick={setPickerRole} />

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

import { useState, type FormEvent } from "react";
import { useGateway } from "./useGateway";
import "./styles.css";

export function App() {
  const { state, events, send } = useGateway(window.bison.gatewayWebSocketUrl);
  const [draft, setDraft] = useState("");

  const submit = (submitEvent: FormEvent) => {
    submitEvent.preventDefault();
    const content = draft.trim();
    if (content.length === 0) {
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
        <span>{window.bison.gatewayWebSocketUrl}</span>
      </div>

      <div className="stream">
        {events.map((event) => (
          <div className="entry" key={`${event.request_id}-${event.sequence}`}>
            <span className="sequence">{event.sequence}</span>
            <span className="type">{event.type}</span>
            <span className="request">{event.request_id}</span>
          </div>
        ))}
      </div>

      <form className="composer" onSubmit={submit}>
        <input
          value={draft}
          onChange={(changeEvent) => setDraft(changeEvent.target.value)}
          placeholder="Send a message"
          autoFocus
        />
        <button type="submit" disabled={state !== "open"}>
          Send
        </button>
      </form>
    </div>
  );
}

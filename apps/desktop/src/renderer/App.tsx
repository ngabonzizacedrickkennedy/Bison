import { useEffect, useRef, useState, type FormEvent } from "react";
import { CapabilityBar } from "./CapabilityBar";
import { useCapabilities } from "./useCapabilities";
import { useGateway } from "./useGateway";
import "./styles.css";

export function App() {
  const { state, historyState, messages, send } = useGateway(
    window.bison.gatewayWebSocketUrl,
    window.bison.gatewayHttpUrl,
  );
  const { manifestState, manifest } = useCapabilities(window.bison.gatewayHttpUrl);
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

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
        <span className="detail">
          {historyState === "loading" && "loading history"}
          {historyState === "failed" && "history unavailable"}
          {historyState === "ready" && `${messages.length} messages`}
        </span>
      </div>

      <CapabilityBar manifestState={manifestState} manifest={manifest} />

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

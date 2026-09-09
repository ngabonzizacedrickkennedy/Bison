import { useState, type FormEvent } from "react";
import type { TaskDraft } from "./tasks";

const KINDS = ["code", "automation", "research", "real_world", "setup", "verification"] as const;

const TITLE_LIMIT = 200;

interface AddTaskProps {
  onAdd: (draft: TaskDraft) => Promise<boolean>;
}

export function AddTask({ onAdd }: AddTaskProps) {
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<string>(KINDS[0]);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = (submitEvent: FormEvent) => {
    submitEvent.preventDefault();

    const trimmed = title.trim();

    if (trimmed === "" || busy) {
      return;
    }

    setBusy(true);

    void onAdd({ title: trimmed, kind, description: description.trim() })
      .then((added) => {
        if (added) {
          setTitle("");
          setDescription("");
        }
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <form className="add-task" onSubmit={submit}>
      <input
        className="add-task-title"
        value={title}
        onChange={(changeEvent) => setTitle(changeEvent.target.value)}
        placeholder="Add a task"
        maxLength={TITLE_LIMIT}
        disabled={busy}
      />

      <select
        className="add-task-kind"
        value={kind}
        onChange={(changeEvent) => setKind(changeEvent.target.value)}
        disabled={busy}
      >
        {KINDS.map((entry) => (
          <option key={entry} value={entry}>
            {entry.replace("_", " ")}
          </option>
        ))}
      </select>

      <input
        className="add-task-description"
        value={description}
        onChange={(changeEvent) => setDescription(changeEvent.target.value)}
        placeholder="what done looks like (optional)"
        disabled={busy}
      />

      <button type="submit" disabled={busy || title.trim() === ""}>
        Add
      </button>
    </form>
  );
}

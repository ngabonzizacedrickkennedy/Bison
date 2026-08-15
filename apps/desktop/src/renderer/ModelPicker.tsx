import { useEffect, useRef, useState } from "react";
import {
  pullModel,
  searchCatalog,
  type CatalogEntry,
  type PullProgress,
  type Role,
} from "./broker";

const SEARCH_LIMIT = 40;
const DEBOUNCE_MS = 200;
const BYTES_PER_GB = 1024 ** 3;

interface ModelPickerProps {
  httpUrl: string;
  role: Role;
  boundModelId: string | null;
  installed: Set<string>;
  onSelect: (modelId: string) => Promise<void>;
  onPulled: () => Promise<void>;
  onClose: () => void;
}

function describeProgress(progress: PullProgress): string {
  if (progress.completedBytes === null || progress.totalBytes === null) {
    return progress.status;
  }

  const done = (progress.completedBytes / BYTES_PER_GB).toFixed(2);
  const total = (progress.totalBytes / BYTES_PER_GB).toFixed(2);

  return `${progress.status} · ${done} / ${total} GB`;
}

function percentOf(progress: PullProgress): number {
  if (
    progress.completedBytes === null ||
    progress.totalBytes === null ||
    progress.totalBytes === 0
  ) {
    return 0;
  }

  return Math.min(100, (progress.completedBytes / progress.totalBytes) * 100);
}

export function ModelPicker({
  httpUrl,
  role,
  boundModelId,
  installed,
  onSelect,
  onPulled,
  onClose,
}: ModelPickerProps) {
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [binding, setBinding] = useState<string | null>(null);
  const [pullingId, setPullingId] = useState<string | null>(null);
  const [progress, setProgress] = useState<PullProgress | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const locked = binding !== null || pullingId !== null;

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const timer = window.setTimeout(() => {
      searchCatalog(httpUrl, query, SEARCH_LIMIT)
        .then((found) => {
          if (!cancelled) {
            setEntries(found);
          }
        })
        .catch((reason: unknown) => {
          if (!cancelled) {
            setError(reason instanceof Error ? reason.message : String(reason));
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [httpUrl, query]);

  const choose = (modelId: string): void => {
    setBinding(modelId);
    setError(null);

    void onSelect(modelId)
      .then(() => {
        onClose();
      })
      .catch((reason: unknown) => {
        setBinding(null);
        setError(reason instanceof Error ? reason.message : String(reason));
      });
  };

  const download = (modelId: string): void => {
    const controller = new AbortController();
    abortRef.current = controller;

    setPullingId(modelId);
    setProgress(null);
    setError(null);

    void pullModel(httpUrl, modelId, setProgress, controller.signal)
      .then(async () => {
        await onPulled();
        setPullingId(null);
        setProgress(null);
      })
      .catch((reason: unknown) => {
        setPullingId(null);
        setProgress(null);

        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
  };

  const dismiss = (): void => {
    abortRef.current?.abort();
    onClose();
  };

  return (
    <div className="picker" onClick={dismiss}>
      <div className="picker-panel" onClick={(clickEvent) => clickEvent.stopPropagation()}>
        <div className="picker-head">
          <span className="picker-role">bind {role}</span>
          <button type="button" className="picker-close" onClick={dismiss}>
            {pullingId !== null ? "cancel" : "close"}
          </button>
        </div>

        <input
          className="picker-search"
          value={query}
          onChange={(changeEvent) => setQuery(changeEvent.target.value)}
          placeholder="search the catalog"
          autoFocus
        />

        {error !== null && <div className="picker-error">{error}</div>}

        <div className="picker-results">
          {entries.length === 0 && <div className="picker-empty">nothing matches</div>}

          {entries.map((entry) => {
            const onDisk = installed.has(entry.model_id);
            const pullable = entry.locality === "local" && !onDisk;
            const active = pullingId === entry.model_id;

            return (
              <div
                className={`picker-entry ${entry.model_id === boundModelId ? "bound" : ""}`}
                key={entry.model_id}
              >
                <button
                  type="button"
                  className="picker-choose"
                  disabled={locked}
                  onClick={() => choose(entry.model_id)}
                >
                  <span className="picker-id">{entry.model_id}</span>
                  <span className="picker-tags">{entry.capability_tags.join(" · ")}</span>
                </button>

                <span className="picker-meta">
                  {entry.locality === "local"
                    ? `${entry.size_gb ?? "?"} GB${onDisk ? " · on disk" : ""}`
                    : entry.provider}
                </span>

                {pullable && (
                  <button
                    type="button"
                    className="picker-pull"
                    disabled={locked}
                    onClick={() => download(entry.model_id)}
                  >
                    download
                  </button>
                )}

                {active && progress !== null && (
                  <div className="picker-progress">
                    <div className="picker-bar">
                      <span style={{ width: `${percentOf(progress)}%` }} />
                    </div>
                    <span className="picker-status">{describeProgress(progress)}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

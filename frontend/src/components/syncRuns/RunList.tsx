import type { SyncRun } from "../../services/api";
import { CHANGE_TYPES, changeCounts, fetchedCount, formatTime } from "./format";

interface RunListProps {
  runs: SyncRun[];
  selectedId: string | null;
  onSelect: (run: SyncRun) => void;
}

export function RunList({ runs, selectedId, onSelect }: RunListProps) {
  if (runs.length === 0) {
    return <p className="empty">No sync runs yet. Run `python -m app.sync` for this tenant.</p>;
  }

  return (
    <ol className="run-list" aria-label="Sync runs">
      {runs.map((run) => {
        const counts = changeCounts(run);
        const fetched = fetchedCount(run);
        return (
          <li key={run.id}>
            <button
              type="button"
              className={run.id === selectedId ? "run selected" : "run"}
              aria-pressed={run.id === selectedId}
              onClick={() => onSelect(run)}
            >
              <span className="run-heading">
                <span className={`status status-${run.status}`}>{run.status}</span>
                <span className="mode">{run.mode} sync</span>
              </span>
              <span className="run-time">{formatTime(run.started_at)}</span>
              <span className="run-counts">
                {fetched !== null && <span>{fetched} fetched</span>}
                {CHANGE_TYPES.map((type) => (
                  <span key={type} className={`badge badge-${type}`}>
                    {counts[type]} {type}
                  </span>
                ))}
              </span>
              {run.error && <span className="run-error">{run.error}</span>}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

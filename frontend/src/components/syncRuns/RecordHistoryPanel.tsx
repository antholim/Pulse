import type { RecordHistory, SyncRun } from "../../services/api";
import { FieldChanges } from "./FieldChanges";
import { formatTime, formatValue } from "./format";

interface RecordHistoryPanelProps {
  history: RecordHistory;
  runs: SyncRun[];
  onClose: () => void;
}

export function RecordHistoryPanel({ history, runs, onClose }: RecordHistoryPanelProps) {
  const runTime = (runId: string) => {
    const run = runs.find((r) => r.id === runId);
    return run ? `${run.mode} sync of ${formatTime(run.started_at)}` : "an earlier sync";
  };
  const current = history.versions[history.versions.length - 1];

  return (
    <section className="history" aria-label="Record history">
      <div className="history-heading">
        <h2>
          {current.label} <span className="kind">{history.kind}</span>
        </h2>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <p className="muted">
        {history.versions.length} version{history.versions.length === 1 ? "" : "s"}, oldest first.
        Nothing is overwritten: each change closes a version and opens a new one.
      </p>
      <ol className="versions">
        {history.versions.map((version, index) => (
          <li key={version.id} className={version.valid_to ? "version closed" : "version current"}>
            <div className="version-heading">
              <strong>Version {index + 1}</strong>
              <span>
                {formatTime(version.valid_from)} to{" "}
                {version.valid_to ? formatTime(version.valid_to) : "now (current)"}
              </span>
            </div>
            <dl className="identifiers">
              <dt>Name</dt>
              <dd>{version.label}</dd>
              <dt>Domain</dt>
              <dd>{formatValue(version.domain)}</dd>
              <dt>LinkedIn</dt>
              <dd>{formatValue(version.linkedin)}</dd>
              {Object.entries(version.external_ids).map(([key, value]) => (
                <div key={key} className="identifier">
                  <dt>{key}</dt>
                  <dd>{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
            {version.events.map((event) => (
              <div key={`${event.sync_run_id}-${event.change_type}`} className="event">
                <p>
                  <span className={`badge badge-${event.change_type}`}>{event.change_type}</span> by
                  the {runTime(event.sync_run_id)}
                </p>
                <FieldChanges fields={event.changed_fields} />
              </div>
            ))}
          </li>
        ))}
      </ol>
    </section>
  );
}

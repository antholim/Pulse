import { useState } from "react";
import type { ChangeType, RecordChange } from "../../services/api";
import { FieldChanges } from "./FieldChanges";
import { CHANGE_TYPES } from "./format";

interface ChangeListProps {
  changes: RecordChange[];
  onOpenRecord: (change: RecordChange) => void;
}

export function ChangeList({ changes, onOpenRecord }: ChangeListProps) {
  const [filter, setFilter] = useState<ChangeType | "all">("all");
  const shown = filter === "all" ? changes : changes.filter((c) => c.change_type === filter);

  return (
    <section aria-label="Changes">
      <div className="filters" role="group" aria-label="Filter changes">
        {(["all", ...CHANGE_TYPES] as const).map((type) => (
          <button
            key={type}
            type="button"
            aria-pressed={filter === type}
            className={filter === type ? "filter active" : "filter"}
            onClick={() => setFilter(type)}
          >
            {type} (
            {type === "all" ? changes.length : changes.filter((c) => c.change_type === type).length}
            )
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <p className="empty">No changes in this run.</p>
      ) : (
        <ul className="change-list">
          {shown.map((change) => (
            <li key={`${change.change_type}-${change.external_id}`} className="change">
              <div className="change-heading">
                <span className={`badge badge-${change.change_type}`}>{change.change_type}</span>
                <span className="kind">{change.kind}</span>
                <button type="button" className="link" onClick={() => onOpenRecord(change)}>
                  {change.label}
                </button>
              </div>
              <FieldChanges fields={change.changed_fields} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

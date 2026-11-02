import type { FieldChange } from "../../services/api";
import { formatValue } from "./format";

export function FieldChanges({ fields }: { fields: Record<string, FieldChange> }) {
  const entries = Object.entries(fields);
  if (entries.length === 0) return null;

  return (
    <table className="field-changes">
      <thead>
        <tr>
          <th scope="col">Field</th>
          <th scope="col">Before</th>
          <th scope="col">After</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([field, change]) => (
          <tr key={field}>
            <td className="field-name">{field}</td>
            <td className="before">{formatValue(change.before)}</td>
            <td className="after">{formatValue(change.after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

import { type FormEvent, useEffect, useState } from "react";
import {
  getRecordHistory,
  getRunChanges,
  getRuns,
  getTenants,
  searchRecords,
  type RecordChange,
  type RecordHistory,
  type RecordSummary,
  type SyncRun,
  type Tenant,
} from "../../services/api";
import { ErrorMessage } from "../ErrorMessage";
import { ChangeList } from "./ChangeList";
import { RecordHistoryPanel } from "./RecordHistoryPanel";
import { RunList } from "./RunList";
import "./SyncRunsPage.css";

export function SyncRunsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [run, setRun] = useState<SyncRun | null>(null);
  const [changes, setChanges] = useState<RecordChange[] | null>(null);
  const [history, setHistory] = useState<RecordHistory | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RecordSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const selectRun = (selected: SyncRun | null, tenant: string | null = tenantId) => {
    setRun(selected);
    setChanges(null);
    setHistory(null);
    if (tenant && selected) {
      getRunChanges(tenant, selected.id).then(setChanges).catch(setError);
    }
  };

  const selectTenant = (id: string) => {
    setTenantId(id);
    setRuns([]);
    setResults(null);
    selectRun(null, id);
    getRuns(id)
      .then((list) => {
        setRuns(list);
        selectRun(list[0] ?? null, id);
      })
      .catch(setError);
  };

  useEffect(() => {
    getTenants()
      .then((list) => {
        setTenants(list);
        if (list.length > 0) selectTenant(list[0].id);
      })
      .catch(setError);
    // Load once on mount; later tenant changes go through selectTenant.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openRecord = (record: { source_id: string; external_id: string }) => {
    if (!tenantId) return;
    getRecordHistory(tenantId, record.source_id, record.external_id)
      .then(setHistory)
      .catch(setError);
  };

  const search = (event: FormEvent) => {
    event.preventDefault();
    if (!tenantId || !query.trim()) return;
    searchRecords(tenantId, query.trim()).then(setResults).catch(setError);
  };

  return (
    <div className="sync-runs-page">
      <div className="toolbar">
        <label>
          Tenant{" "}
          <select
            value={tenantId ?? ""}
            onChange={(event) => selectTenant(event.target.value)}
            disabled={tenants.length === 0}
          >
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </label>
        <form onSubmit={search} role="search">
          <input
            type="search"
            aria-label="Search records by name"
            placeholder="Search a record by name"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit">Search</button>
        </form>
      </div>

      {error !== null && <ErrorMessage error={error} />}

      {results !== null && (
        <section className="results" aria-label="Search results">
          {results.length === 0 ? (
            <p className="empty">No current record matches.</p>
          ) : (
            <ul>
              {results.map((record) => (
                <li key={`${record.source_id}-${record.external_id}`}>
                  <button type="button" className="link" onClick={() => openRecord(record)}>
                    {record.label}
                  </button>{" "}
                  <span className="kind">{record.kind}</span>
                  {record.domain && <span className="muted"> {record.domain}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <div className="columns">
        <aside>
          <h2>Sync runs</h2>
          <RunList runs={runs} selectedId={run?.id ?? null} onSelect={(r) => selectRun(r)} />
        </aside>
        <section className="details">
          {history ? (
            <RecordHistoryPanel history={history} runs={runs} onClose={() => setHistory(null)} />
          ) : run ? (
            <>
              <h2>What changed in this run</h2>
              {changes === null ? (
                <p className="muted">Loading changes...</p>
              ) : (
                <ChangeList changes={changes} onOpenRecord={openRecord} />
              )}
            </>
          ) : (
            <p className="empty">Select a sync run to see what changed.</p>
          )}
        </section>
      </div>
    </div>
  );
}

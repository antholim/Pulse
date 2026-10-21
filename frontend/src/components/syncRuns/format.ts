import type { ChangeType, SyncRun } from "../../services/api";

export const CHANGE_TYPES: ChangeType[] = ["added", "modified", "removed"];

export function formatTime(value: string | null): string {
  if (!value) return "now";
  return new Date(value).toLocaleString("en-CA", {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(empty)";
  if (typeof value === "string") return value;
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value.length ? value.join(", ") : "(empty)";
  }
  return JSON.stringify(value);
}

export function changeCounts(run: SyncRun): Record<ChangeType, number> {
  const changes = run.counts.changes ?? {};
  return {
    added: changes.added ?? 0,
    modified: changes.modified ?? 0,
    removed: changes.removed ?? 0,
  };
}

export function fetchedCount(run: SyncRun): number | null {
  const fetched = run.counts.fetched;
  return typeof fetched === "number" ? fetched : null;
}

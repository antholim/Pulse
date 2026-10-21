import { logger } from "./logger";

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: { status: number | null; code: string; requestId?: string | null },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId ?? null;
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; request_id?: string | null };
}

export interface Health {
  status: string;
  service: string;
}

function failed(path: string, error: ApiError): ApiError {
  logger.warn("api_request_failed", {
    path,
    status: error.status,
    code: error.code,
    requestId: error.requestId,
  });
  return error;
}

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw failed(
      path,
      new ApiError("Cannot reach the PULSE server.", { status: null, code: "network_error" }),
    );
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ErrorBody | null;
    throw failed(
      path,
      new ApiError(body?.error?.message ?? `Request failed with status ${response.status}`, {
        status: response.status,
        code: body?.error?.code ?? "http_error",
        requestId: body?.error?.request_id ?? null,
      }),
    );
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export type ChangeType = "added" | "modified" | "removed";

export interface FieldChange {
  before: unknown;
  after: unknown;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string | null;
}

export interface SyncRun {
  id: string;
  source_id: string;
  mode: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  counts: Record<string, unknown> & { changes?: Partial<Record<ChangeType, number>> };
  error: string | null;
}

export interface RecordChange {
  change_type: ChangeType;
  kind: string;
  source_id: string;
  external_id: string;
  label: string;
  changed_fields: Record<string, FieldChange>;
}

export interface RecordSummary {
  source_id: string;
  external_id: string;
  kind: string;
  label: string;
  domain: string | null;
  linkedin: string | null;
  valid_from: string;
}

export interface VersionEvent {
  sync_run_id: string;
  change_type: ChangeType;
  changed_fields: Record<string, FieldChange>;
}

export interface RecordVersion {
  id: string;
  label: string;
  name_normalized: string | null;
  domain: string | null;
  linkedin: string | null;
  external_ids: Record<string, unknown>;
  valid_from: string;
  valid_to: string | null;
  first_seen_run: string;
  removed_run: string | null;
  events: VersionEvent[];
}

export interface RecordHistory {
  source_id: string;
  external_id: string;
  kind: string;
  versions: RecordVersion[];
}

export function getTenants(): Promise<Tenant[]> {
  return request<Tenant[]>("/api/tenants");
}

export function getRuns(tenantId: string): Promise<SyncRun[]> {
  return request<SyncRun[]>(`/api/tenants/${tenantId}/runs`);
}

export function getRunChanges(tenantId: string, runId: string): Promise<RecordChange[]> {
  return request<RecordChange[]>(`/api/tenants/${tenantId}/runs/${runId}/changes`);
}

export function searchRecords(tenantId: string, query: string): Promise<RecordSummary[]> {
  const params = new URLSearchParams({ q: query });
  return request<RecordSummary[]>(`/api/tenants/${tenantId}/records?${params}`);
}

export function getRecordHistory(
  tenantId: string,
  sourceId: string,
  externalId: string,
): Promise<RecordHistory> {
  return request<RecordHistory>(
    `/api/tenants/${tenantId}/records/${sourceId}/${encodeURIComponent(externalId)}`,
  );
}

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

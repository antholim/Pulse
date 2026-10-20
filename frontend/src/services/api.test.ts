import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getHealth } from "./api";
import { logger } from "./logger";

const errorBody = {
  error: {
    code: "service_unavailable",
    message: "Database unavailable",
    details: null,
    request_id: "abc123",
  },
};

describe("getHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns the backend health status", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: "ok", service: "pulse-backend" }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getHealth()).resolves.toEqual({ status: "ok", service: "pulse-backend" });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/health$/));
  });

  it("turns the standard error body into an ApiError", async () => {
    vi.spyOn(logger, "warn").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(errorBody), { status: 503 })),
    );

    const error = await getHealth().catch((err: unknown) => err);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 503,
      code: "service_unavailable",
      message: "Database unavailable",
      requestId: "abc123",
    });
  });

  it("still fails cleanly when the error body is not JSON", async () => {
    vi.spyOn(logger, "warn").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 502 })));

    await expect(getHealth()).rejects.toMatchObject({
      status: 502,
      code: "http_error",
      message: "Request failed with status 502",
      requestId: null,
    });
  });

  it("reports a network failure as a network_error", async () => {
    vi.spyOn(logger, "warn").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(getHealth()).rejects.toMatchObject({ status: null, code: "network_error" });
  });

  it("logs failed requests with their request id", async () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(errorBody), { status: 503 })),
    );

    await getHealth().catch(() => {});

    expect(warn).toHaveBeenCalledWith("api_request_failed", {
      path: "/api/health",
      status: 503,
      code: "service_unavailable",
      requestId: "abc123",
    });
  });
});

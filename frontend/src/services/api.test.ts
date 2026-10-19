import { afterEach, describe, expect, it, vi } from "vitest";

import { getHealth } from "./api";

describe("getHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
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

  it("throws when the backend answers with an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

    await expect(getHealth()).rejects.toThrow("Failed to fetch health status");
  });
});

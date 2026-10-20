import { afterEach, describe, expect, it, vi } from "vitest";

import { createLogger, installGlobalErrorLogging, logger, resolveLogLevel } from "./logger";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("resolveLogLevel", () => {
  it("uses a valid configured level", () => {
    expect(resolveLogLevel(" WARN ", true)).toBe("warn");
  });

  it("defaults to debug in development and warn in production", () => {
    expect(resolveLogLevel(undefined, true)).toBe("debug");
    expect(resolveLogLevel(undefined, false)).toBe("warn");
  });

  it("ignores unknown levels", () => {
    expect(resolveLogLevel("toString", false)).toBe("warn");
  });
});

describe("createLogger", () => {
  it("writes a structured entry through the matching console method", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    createLogger("debug").warn("api_request_failed", { status: 503 });

    expect(warn).toHaveBeenCalledWith(
      "[PULSE] api_request_failed",
      expect.objectContaining({
        level: "warn",
        message: "api_request_failed",
        status: 503,
        timestamp: expect.any(String),
      }),
    );
  });

  it("drops entries below the minimum level", () => {
    const debug = vi.spyOn(console, "debug").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});

    const log = createLogger("error");
    log.debug("noise");
    log.error("broken");

    expect(debug).not.toHaveBeenCalled();
    expect(error).toHaveBeenCalledOnce();
  });
});

describe("installGlobalErrorLogging", () => {
  it("logs uncaught errors and unhandled promise rejections", () => {
    const target = new EventTarget();
    const logError = vi.spyOn(logger, "error").mockImplementation(() => {});

    installGlobalErrorLogging(target);
    target.dispatchEvent(new ErrorEvent("error", { message: "boom" }));
    target.dispatchEvent(
      Object.assign(new Event("unhandledrejection"), { reason: new Error("nope") }),
    );

    expect(logError).toHaveBeenCalledWith("uncaught_error", { error: "boom" });
    expect(logError).toHaveBeenCalledWith("unhandled_rejection", { error: "nope" });
  });
});

import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { toUserMessage } from "./errors";

describe("toUserMessage", () => {
  it("explains network and server failures in plain language", () => {
    expect(toUserMessage(new ApiError("x", { status: null, code: "network_error" }))).toBe(
      "We can't reach the PULSE server. Check your connection and try again.",
    );
    expect(toUserMessage(new ApiError("x", { status: 500, code: "internal_error" }))).toBe(
      "Something went wrong on our side. Please try again in a moment.",
    );
  });

  it("shows the server's message for other API errors", () => {
    const error = new ApiError("Organization 7 not found", { status: 404, code: "not_found" });

    expect(toUserMessage(error)).toBe("Organization 7 not found");
  });

  it("hides the raw status text of a server error with no error body", () => {
    const error = new ApiError("Request failed with status 502", {
      status: 502,
      code: "http_error",
    });

    expect(toUserMessage(error)).toBe(
      "Something went wrong on our side. Please try again in a moment.",
    );
  });

  it("keeps the status text of a client error with no error body", () => {
    const error = new ApiError("Request failed with status 413", {
      status: 413,
      code: "http_error",
    });

    expect(toUserMessage(error)).toBe("Request failed with status 413");
  });

  it("falls back to a generic message for unknown errors", () => {
    expect(toUserMessage(new Error("undefined is not a function"))).toBe(
      "Something went wrong. Please try again.",
    );
  });
});

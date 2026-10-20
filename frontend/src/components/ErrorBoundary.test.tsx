import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { logger } from "../services/logger";
import { ErrorBoundary } from "./ErrorBoundary";

function Broken(): never {
  throw new Error("render failed");
}

describe("ErrorBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a fallback and logs the error when a child crashes", () => {
    // React reports caught render errors to console.error as well.
    vi.spyOn(console, "error").mockImplementation(() => {});
    const logError = vi.spyOn(logger, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong.");
    expect(logError).toHaveBeenCalledWith(
      "ui_render_failed",
      expect.objectContaining({ error: "render failed" }),
    );
  });

  it("renders its children when nothing fails", () => {
    render(
      <ErrorBoundary>
        <p>All good</p>
      </ErrorBoundary>,
    );

    expect(screen.getByText("All good")).toBeInTheDocument();
  });
});

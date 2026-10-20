import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "../services/api";
import { ErrorMessage } from "./ErrorMessage";

describe("ErrorMessage", () => {
  it("shows a friendly message and the reference id", () => {
    const error = new ApiError("Database unavailable", {
      status: 503,
      code: "service_unavailable",
      requestId: "abc123",
    });

    render(<ErrorMessage error={error} />);

    expect(screen.getByRole("alert")).toHaveTextContent("PULSE is temporarily unavailable");
    expect(screen.getByText("Reference: abc123")).toBeInTheDocument();
  });

  it("omits the reference when there is none", () => {
    render(<ErrorMessage error={new Error("x")} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong.");
    expect(screen.queryByText(/Reference/)).not.toBeInTheDocument();
  });
});

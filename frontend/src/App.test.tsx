import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiError, getHealth } from "./services/api";

vi.mock("./services/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./services/api")>()),
  getHealth: vi.fn(),
}));

describe("App", () => {
  it("shows the backend status once it loads", async () => {
    vi.mocked(getHealth).mockResolvedValue({ status: "ok", service: "pulse-backend" });

    render(<App />);

    expect(screen.getByText("Backend status: Connecting...")).toBeInTheDocument();
    expect(await screen.findByText("Backend status: ok")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("tells the user when the backend is unavailable", async () => {
    vi.mocked(getHealth).mockRejectedValue(
      new ApiError("Cannot reach the PULSE server.", { status: null, code: "network_error" }),
    );

    render(<App />);

    expect(await screen.findByText("Backend status: Backend unavailable")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("We can't reach the PULSE server");
  });
});

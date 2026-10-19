import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";
import { getHealth } from "./services/api";

vi.mock("./services/api", () => ({ getHealth: vi.fn() }));

describe("App", () => {
  it("shows the backend status once it loads", async () => {
    vi.mocked(getHealth).mockResolvedValue({ status: "ok" });

    render(<App />);

    expect(screen.getByText("Backend status: Connecting...")).toBeInTheDocument();
    expect(await screen.findByText("Backend status: ok")).toBeInTheDocument();
  });

  it("tells the user when the backend is unavailable", async () => {
    vi.mocked(getHealth).mockRejectedValue(new Error("down"));

    render(<App />);

    expect(await screen.findByText("Backend status: Backend unavailable")).toBeInTheDocument();
  });
});

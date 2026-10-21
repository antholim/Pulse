import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  getRecordHistory,
  getRunChanges,
  getRuns,
  getTenants,
  searchRecords,
  type RecordChange,
  type RecordHistory,
  type SyncRun,
} from "../../services/api";
import { SyncRunsPage } from "./SyncRunsPage";

vi.mock("../../services/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/api")>()),
  getTenants: vi.fn(),
  getRuns: vi.fn(),
  getRunChanges: vi.fn(),
  getRecordHistory: vi.fn(),
  searchRecords: vi.fn(),
}));

const TENANT = { id: "t1", name: "Média démo Capitale", slug: "demo-capitale" };

function run(id: string, mode: string, changes: Record<string, number>): SyncRun {
  return {
    id,
    source_id: "s1",
    mode,
    status: "succeeded",
    started_at: "2026-11-01T12:00:00Z",
    finished_at: "2026-11-01T12:00:05Z",
    counts: { fetched: 500, changes },
    error: null,
  };
}

const SECOND = run("r2", "incremental", { added: 1, modified: 1, removed: 0 });
const FIRST = run("r1", "full", { added: 2, modified: 0, removed: 0 });

const CHANGES: RecordChange[] = [
  {
    change_type: "added",
    kind: "person",
    source_id: "s1",
    external_id: "p9",
    label: "Émilie Gagnon",
    changed_fields: {},
  },
  {
    change_type: "modified",
    kind: "organization",
    source_id: "s1",
    external_id: "o1",
    label: "Groupe Tremblay inc.",
    changed_fields: { domain: { before: "tremblay.ca", after: "groupe-tremblay.com" } },
  },
];

const HISTORY: RecordHistory = {
  source_id: "s1",
  external_id: "o1",
  kind: "organization",
  versions: [
    {
      id: "v1",
      label: "Groupe Tremblay inc.",
      name_normalized: "groupe tremblay",
      domain: "tremblay.ca",
      linkedin: null,
      external_ids: {},
      valid_from: "2026-11-01T11:00:00Z",
      valid_to: "2026-11-01T12:00:00Z",
      first_seen_run: "r1",
      removed_run: null,
      events: [{ sync_run_id: "r1", change_type: "added", changed_fields: {} }],
    },
    {
      id: "v2",
      label: "Groupe Tremblay inc.",
      name_normalized: "groupe tremblay",
      domain: "groupe-tremblay.com",
      linkedin: null,
      external_ids: { crm_id: ["CRM-12345"] },
      valid_from: "2026-11-01T12:00:00Z",
      valid_to: null,
      first_seen_run: "r2",
      removed_run: null,
      events: [
        {
          sync_run_id: "r2",
          change_type: "modified",
          changed_fields: { domain: { before: "tremblay.ca", after: "groupe-tremblay.com" } },
        },
      ],
    },
  ],
};

describe("SyncRunsPage", () => {
  beforeEach(() => {
    vi.mocked(getTenants).mockResolvedValue([TENANT]);
    vi.mocked(getRuns).mockResolvedValue([SECOND, FIRST]);
    vi.mocked(getRunChanges).mockResolvedValue(CHANGES);
    vi.mocked(getRecordHistory).mockResolvedValue(HISTORY);
  });

  it("lists the runs and shows the latest run's changes with field diffs", async () => {
    // Act
    render(<SyncRunsPage />);

    // Assert
    const runs = await screen.findByRole("list", { name: "Sync runs" });
    expect(within(runs).getAllByRole("button")).toHaveLength(2);
    expect(within(runs).getByText("incremental sync")).toBeInTheDocument();
    expect(await screen.findByText("Groupe Tremblay inc.")).toBeInTheDocument();
    expect(screen.getByText("tremblay.ca")).toBeInTheDocument();
    expect(screen.getByText("groupe-tremblay.com")).toBeInTheDocument();
    expect(getRunChanges).toHaveBeenCalledWith("t1", "r2");
  });

  it("filters the changes by type", async () => {
    // Arrange
    render(<SyncRunsPage />);
    await screen.findByText("Émilie Gagnon");

    // Act
    fireEvent.click(screen.getByRole("button", { name: "modified (1)" }));

    // Assert
    expect(screen.queryByText("Émilie Gagnon")).not.toBeInTheDocument();
    expect(screen.getByText("Groupe Tremblay inc.")).toBeInTheDocument();
  });

  it("loads another run's changes when it is selected", async () => {
    // Arrange
    render(<SyncRunsPage />);
    const runs = await screen.findByRole("list", { name: "Sync runs" });

    // Act
    fireEvent.click(within(runs).getByText("full sync"));

    // Assert
    expect(getRunChanges).toHaveBeenLastCalledWith("t1", "r1");
  });

  it("opens a record's history from a change", async () => {
    // Arrange
    render(<SyncRunsPage />);

    // Act
    fireEvent.click(await screen.findByRole("button", { name: "Groupe Tremblay inc." }));

    // Assert
    const history = await screen.findByRole("region", { name: "Record history" });
    expect(within(history).getByText("Version 1")).toBeInTheDocument();
    expect(within(history).getByText("Version 2")).toBeInTheDocument();
    expect(within(history).getByText("CRM-12345")).toBeInTheDocument();
    expect(getRecordHistory).toHaveBeenCalledWith("t1", "s1", "o1");
  });

  it("searches records by name and opens one", async () => {
    // Arrange
    vi.mocked(searchRecords).mockResolvedValue([
      {
        source_id: "s1",
        external_id: "o1",
        kind: "organization",
        label: "Groupe Tremblay inc.",
        domain: "groupe-tremblay.com",
        linkedin: null,
        valid_from: "2026-11-01T12:00:00Z",
      },
    ]);
    render(<SyncRunsPage />);
    await screen.findByRole("list", { name: "Sync runs" });

    // Act
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "tremblay" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const results = await screen.findByRole("region", { name: "Search results" });
    fireEvent.click(within(results).getByRole("button", { name: "Groupe Tremblay inc." }));

    // Assert
    expect(searchRecords).toHaveBeenCalledWith("t1", "tremblay");
    expect(await screen.findByRole("region", { name: "Record history" })).toBeInTheDocument();
  });

  it("says when a tenant has no runs yet", async () => {
    // Arrange
    vi.mocked(getRuns).mockResolvedValue([]);

    // Act
    render(<SyncRunsPage />);

    // Assert
    expect(await screen.findByText(/No sync runs yet/)).toBeInTheDocument();
  });

  it("shows an error when the API fails", async () => {
    // Arrange
    vi.mocked(getTenants).mockRejectedValue(
      new ApiError("Database unavailable", { status: 503, code: "service_unavailable" }),
    );

    // Act
    render(<SyncRunsPage />);

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
  });
});

# Synthetic Omerlo data

**Everything generated here is synthetic.** No real person or organization is in it. Names are built from common Quebec surnames, sectors and places, phone numbers use the fictional `555` exchange, and media sites use `.example` domains.

Use it for development, tests and demos. Under Law 25, real client data never goes into the repo or into AI tools. Do **not** use it for the official entity resolution evaluation: that needs real, sponsor-approved data (see [#61](https://github.com/antholim/Pulse/issues/61) and the RESOLVE epic).

## Generate

```bash
cd backend
uv run python -m synthetic.omerlo_fixtures                     # seed 490, writes synthetic/out/
uv run python -m synthetic.omerlo_fixtures --seed 7 --out /tmp/omerlo --schemas /tmp/schemas
```

The same seed always gives byte-identical files. `synthetic/out/` is git-ignored: regenerate instead of committing.

## Output

```
out/
  manifest.json                       seed, counts, the synthetic notice
  demo-capitale/                      one folder per tenant
    workspaces.json  categories.json
    organizations.json  people.json  projects.json  events.json  event_sessions.json
    metadata.json                     record id -> metadata entries (key and value)
    ground_truth.dev_only.json        the deliberate duplicates (dev only)
  demo-estrie/
    ...
```

Files hold **detail** records, in the shapes of the Omerlo backoffice API (see the wiki page [Omerlo API](https://github.com/antholim/Pulse/wiki/Omerlo-API)). `omerlo_schema.summarize` derives the shorter shape that list endpoints return.

Per tenant: about 150 organizations, 300 people, 60 events with 1 to 3 sessions each, and 20 projects. `demo-capitale` has two workspaces and `demo-estrie` one; records carry their workspace in `profile.workspace_id`. Contact, address and description have one entry per locale: about half of the records are French only, 40 percent bilingual and 10 percent English only. A quarter of the organizations exist in both tenants, under different ids.

Metadata is served apart from the records, as it is by the API. About half of the companies carry a `crm_id` there, which entity resolution can use as an external id.

## Deliberate duplicates

About 12 percent of organizations and 4 percent of people get a second record, spelled the way another source might spell it, sometimes in another workspace of the same tenant:

| Change | Example |
|--------|---------|
| `suffix` | `Groupe Leblanc s.e.n.c.` / `Groupe Leblanc senc` |
| `accents` | `Coopérative de Rimouski` / `Cooperative de Rimouski` |
| `case` | `Transport Gosselin inc.` / `TRANSPORT GOSSELIN INC.` |
| `hyphen` | `Groupe St-Pierre` / `Groupe St Pierre` |
| `ampersand` | `Lévesque & Cloutier Avocats` / `Lévesque et Cloutier Avocats` |
| `missing_domain`, `missing_linkedin`, `missing_crm_id` | the duplicate lacks that identifier |

Some pairs still share a domain, LinkedIn URL or CRM id (Tier 1 can find them); others share none (only fuzzy matching can).

`ground_truth.dev_only.json` maps every organization and person record to an entity key, and lists each duplicate pair with its changes. Organization keys are the same across tenants, so the cross-tenant overlap is known too.

## Schemas

`omerlo_schema.py` defines each resource as a strict Pydantic model, for the detail and the list shapes; unknown fields fail validation. `--schemas DIR` exports them as JSON Schema.

Shapes follow the [backoffice documentation](https://developers.omerlo.com/docs/backoffice). Two links are assumptions until checked on staging ([#23](https://github.com/antholim/Pulse/issues/23)): a session speaker's `actor_id` is a person id, and a project's `owner_id` is an organization id.

## Mock Omerlo server

`mock_omerlo.py` serves the fixtures like the Omerlo backoffice API, so the connector can run against it without staging: an `x-api-key` per tenant, community lists scoped by workspace that return summaries and sort with `sort_by`, detail and metadata endpoints, and `{"error": ...}` bodies on errors. The ground truth is never served.

How the real API paginates is not documented yet ([#23](https://github.com/antholim/Pulse/issues/23)). The mock takes `limit` on every list and answers with an opaque `meta.next` cursor, sent back as `after`.

```bash
docker compose --profile mock up mock-omerlo          # or: --profile full for the whole stack
# without Docker:
cd backend && uv run python -m synthetic.mock_omerlo  # --fixtures synthetic/out to serve files
```

When the whole stack runs in Docker (`--profile full`), the `backend` service already points at the mock (`http://mock-omerlo:8100/api`) unless `.env` sets `OMERLO_*`. Leave them unset in `.env`, or set them to staging: `localhost` inside the backend container is the backend itself, not the mock.

For a backend or script running outside Docker, point the connector at it with:

```
OMERLO_BASE_URL=http://localhost:8100/api
OMERLO_API_KEY=mock-demo-capitale        # or mock-demo-estrie
```

Interactive API docs are at http://localhost:8100/docs. In tests, the `mock_omerlo` fixture in `tests/synthetic/conftest.py` gives a `TestClient` over small fixtures.

| Path (under `/api`) | Returns |
|------|---------|
| `GET /composer/v2/workspaces` | The tenant's workspaces (summaries) |
| `GET /composer/v2/workspaces/{id}` | One workspace, with its statuses |
| `GET /core/v2/categories`, `/core/v2/categories/{id}` | Categories, in full |
| `GET /community/v2/workspaces/{workspace_id}/{organizations,people,projects,events}` | Summaries; `sort_by`, `profile_type_ids[]` |
| `GET /community/v2/{organizations,people,projects,events}/{id}` | The full record |
| `GET /community/v2/{organizations,people,projects,events}/{id}/metadata` | Its key and value entries |
| `GET /community/v2/events/{id}/sessions` | The event's sessions |

## Mutations between syncs

`mutate.py` changes the fixtures in a known way, so a second sync has something to find: the "run sync twice, see what changed" demo, and the expected diff for change detection ([#60](https://github.com/antholim/Pulse/issues/60)).

```bash
cd backend
uv run python -m synthetic.omerlo_fixtures                    # sync 1 reads these
uv run python -m synthetic.mutate --set demo                  # then sync 2 sees the changes
uv run python -m synthetic.mutate --reset                     # back to the generated files
uv run python -m synthetic.mutate --list
uv run python -m synthetic.mutate --set demo --fixtures /tmp/omerlo
```

A mutation set is data in `mutate.py`: a name, a description and steps.

| Step | Effect |
|------|--------|
| `Add(kind, count)` | New organizations or people, built like the generated ones (new organizations are new entities in the ground truth) |
| `Edit(kind, fields, count)` | Changes `fields` on `count` records; one field or several at once |
| `Delete(kind, count)` | Removes organizations, people or events (with their sessions) |

Fields that can be edited:

- organizations: `name`, `domain` (canonical URL, website and email in every locale), `linkedin`, `crm_id` (metadata), `phone`
- people: `last_name`, `job_title`, `email`, `linkedin`

Records are picked by an RNG seeded with the set and tenant, among records sorted by id that no earlier step touched, so the same set on the same fixtures always gives byte-identical files. Deletes skip records still referenced (project owners, session speakers) and records in a deliberate duplicate pair, so the ground truth stays consistent; it is updated for adds and deletes.

Every added or edited record gets an `updated_at` after every record already in the fixtures (one day after the latest, one minute apart), so an incremental sync sorted by `updated_at-desc` sees it. A metadata change also bumps its record's `updated_at`. Changed records are validated against the schema models.

The `demo` set, in each tenant: adds 2 organizations and 3 people; edits organizations by name, domain, LinkedIn, CRM id, phone and one by name, domain, LinkedIn and CRM id together; edits people by job title, by last name and email, and by LinkedIn; deletes 1 organization, 2 people and 1 event.

Each set writes `expected_diff.<set>.json` next to the fixtures:

```json
{
  "mutation_set": "demo",
  "changed_after": "2026-10-01T00:00:00Z",
  "tenants": {
    "demo-capitale": {
      "added":    [{"kind": "organizations", "id": "...", "label": "...", "updated_at": "..."}],
      "modified": [{"kind": "organizations", "id": "...", "label": "...", "updated_at": "...",
                    "fields": ["contact", "metadata", "name", "profile"],
                    "changes": [{"field": "contact[fr].linkedin", "before": "...", "after": "..."},
                                {"field": "metadata.crm_id", "before": "...", "after": "..."}]}],
      "removed":  [{"kind": "events", "id": "...", "label": "..."}]
    }
  }
}
```

`changed_after` is the latest `updated_at` before the set, so every change is after it. `fields` lists the top-level fields that changed (`metadata` for metadata entries); `changes` gives each leaf, with per-locale entries keyed by locale (`contact[fr].phone`). Lists are sorted by kind, then id.

The first set applied copies the files to `.original/`; `--reset` restores them, deletes the expected diffs and removes `.original/`. Sets stack (each diff is against the state before it), but one set cannot be applied twice without a reset. `manifest.json` lists the applied sets under `mutations`.

The mock server started with `--fixtures` reloads them when `manifest.json` changes, which `mutate` and `--reset` write last, so a running mock serves the mutated data without a restart.

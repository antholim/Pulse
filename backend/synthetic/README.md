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

`mock_omerlo.py` serves the fixtures like the Reader API, so the connector can run against it without staging: an OAuth 2 client credentials token endpoint, `Authorization: Bearer` and `x-omerlo-media-id` checks, data scoped to the media id, and cursor pagination (`before`, `after`, `limit`, `meta.next`) ordered by `updated_at`. The ground truth is never served.

```bash
docker compose --profile mock up mock-omerlo          # or: --profile full for the whole stack
# without Docker:
cd backend && uv run python -m synthetic.mock_omerlo  # --fixtures synthetic/out to serve files
```

When the whole stack runs in Docker (`--profile full`), the `backend` service already points at the mock (`http://mock-omerlo:8100`) unless `.env` sets `OMERLO_*`. Leave them unset in `.env`, or set them to staging: `localhost` inside the backend container is the backend itself, not the mock.

For a backend or script running outside Docker, point the connector at it with:

```
OMERLO_BASE_URL=http://localhost:8100
OMERLO_TOKEN_URL=http://localhost:8100/oauth/token
OMERLO_CLIENT_ID=mock-client
OMERLO_CLIENT_SECRET=mock-secret
OMERLO_MEDIA_ID=demo-capitale        # or demo-estrie
```

Interactive API docs are at http://localhost:8100/docs. In tests, the `mock_omerlo` fixture in `tests/synthetic/conftest.py` gives a `TestClient` over small fixtures.

| Path | Returns |
|------|---------|
| `POST /oauth/token` | Bearer token (`grant_type=client_credentials`) |
| `GET /api/media/v1/categories`, `/profile_types` | Paginated list |
| `GET /api/media/v1/community/{organizations,people,projects,events}` | Paginated list |
| `GET /api/media/v1/contents` | Paginated summaries (no blocks), categories in `assocs` |
| `GET <any list path>/{id}` | One record; contents include their blocks |
| `GET /api/media/v1/community/events/{id}/participants/people` | Paginated people |

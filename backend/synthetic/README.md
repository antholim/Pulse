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
  demo-capitale/                      one folder per tenant (Omerlo media id)
    categories.json  profile_types.json  organizations.json  people.json
    projects.json  events.json  contents.json
    participants.json                 event id -> person ids
    ground_truth.dev_only.json        the deliberate duplicates (dev only)
  demo-estrie/
    ...
```

Per tenant: about 150 organizations, 300 people, 1,000 contents, 60 events and 20 projects. About 10 percent of contents are sponsored or advertising, and about a third carry a Profiles block linking organizations and people. A quarter of the organizations exist in both tenants, under different ids.

## Deliberate duplicates

About 12 percent of organizations and 4 percent of people get a second record, spelled the way another source might spell it:

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

`omerlo_schema.py` defines each resource as a strict Pydantic model; unknown fields fail validation. `--schemas DIR` exports them as JSON Schema.

Organization, Person and Content follow the fields on developers.omerlo.com. The shapes of Event, Project, Category, ProfileType and content blocks are assumptions until checked on staging ([#23](https://github.com/antholim/Pulse/issues/23)).

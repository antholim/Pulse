# Ticket generator

Creates and updates the project's GitHub epics and issues from one Python file, so the backlog stays consistent (same sections, labels, milestones and story points on every ticket).

| File | Purpose |
|---|---|
| `data.py` | All ticket content: epics, issues, labels, iterations, releases |
| `build.py` | Renders the tickets and syncs them with GitHub |
| `state.json` | Maps each ticket key (`E3`, `S1-12`) to its GitHub issue number, plus a hash of the body last written. **Commit it after every run and never delete it**, or the next run creates duplicates. |
| `out/` | Rendered bodies from the last run, for previewing (git-ignored) |

## Requirements

- Python 3.9 or newer
- [GitHub CLI](https://cli.github.com) logged in (`gh auth login`) with **write** access to `antholim/Pulse`

## Usage

Run from this folder:

```bash
python build.py            # dry run: render to out/, validate, show what would change
python build.py --apply    # create labels and missing issues, update changed bodies, link sub-issues
```

Always run the dry run first and read the plan it prints.

## Adding tickets for a new release

1. In `data.py`, add issues to `ISSUES` with the next key series (`S2-01`, `S2-02`, ... for Release 2). Set `epic`, `iteration` (5 to 8 for Release 2), `kind` (`code`, `docs` or `spike`) and `points` (1, 2, 3, 5, 8 or 13).
2. Add the release label to `NEW_LABELS` (for example `("Release 2", "B60205", "Planned for Release 2 (Iteration 8, due Feb 5, 2027)")`).
3. Reference other tickets with tokens such as `{E3}` or `{S1-12}`; they become `#N` links.
4. Start an acceptance criterion or task with `[x] ` to render it already checked.
5. Run the dry run, then `--apply`, then commit `data.py` and `state.json`.

The issue's release label and its parent epic's "Release N issues" section with point totals are generated from `iteration`.

## Editing tickets

Change the ticket in `data.py` and re-run. The script only overwrites a body it wrote itself.

If someone edited an issue on GitHub (ticked a checkbox, added notes), the script detects it and **skips** that issue instead of erasing the edit. To update it again, copy the GitHub changes into `data.py`. Once the rendered body matches GitHub, the next `--apply` adopts it and later changes flow through again.

Titles, milestones (from `iteration`) and labels are synced too, with the same protection:

- A title or milestone is only changed if GitHub still shows the value the script last wrote (kept under `meta` in `state.json`). If someone changed it by hand, or the script never recorded it ("not tracked yet"), the dry run reports it and `--apply` skips it. Either copy the GitHub value into `data.py`, or run `python build.py --apply --overwrite S1-09` (comma-separated keys, `--overwrite=S1-09` works too) to apply the value from `data.py`.
- Labels listed in `data.py` are added. A label is only removed if the script added it and `data.py` no longer lists it, so labels added by hand are never touched, even when `data.py` lists them too.

Run `python build.py --help` for all options.

For backlog changes, merge the `data.py` change first and run `--apply` from `main`, so the review happens before anything changes on GitHub.

Assignees are never set by the script.

## Writing style

No em or en dashes in ticket text; the dry run flags them.

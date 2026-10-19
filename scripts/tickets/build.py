"""Render, create and update the PULSE GitHub tickets defined in data.py.

    python build.py           dry run: render bodies to out/, validate, and
                              show what --apply would create or update
    python build.py --apply   create labels and missing issues, update changed
                              bodies, titles, milestones and labels, link
                              issues to their parent epics
    --overwrite S1-09,S1-10   also apply data.py's title and milestone to these
                              keys when they were changed on GitHub by hand

See README.md for details.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from data import EPICS, ISSUES, ITERATIONS, NEW_LABELS, RELEASES

REPO = "antholim/Pulse"
GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"
HERE = Path(__file__).parent
OUT = HERE / "out"
STATE_FILE = HERE / "state.json"

EPIC_BY_KEY = {e["key"]: e for e in EPICS}
ISSUE_BY_KEY = {i["key"]: i for i in ISSUES}
ALL_BY_KEY = {**EPIC_BY_KEY, **ISSUE_BY_KEY}
TOKEN = re.compile(r"\{(E\d+|S\d+-\d+)\}")

DOD = {
    "code": [
        "Acceptance criteria met",
        "PR reviewed by at least one teammate and linked with `Closes #<this issue>`",
        "CI green (lint, tests, coverage)",
        "Wiki updated",
    ],
    "docs": [
        "Acceptance criteria met",
        "Reviewed by at least one teammate",
        "Published in the wiki and linked from the wiki home page",
    ],
    "spike": [
        "Decision and reasoning documented in the wiki",
        "Reviewed with the team (and the sponsor where relevant)",
        "Follow-up issues created for the work it unblocks",
    ],
}

PRIORITY_TEXT = {
    "must": "**MUST** in the proposal's MVP boundary.",
    "should": "**SHOULD** in the proposal's MVP boundary.",
    "could": "**COULD** in the proposal's MVP boundary: only after the core workflow is stable.",
}


# ------------------------------------------------------------------ rendering

def is_epic(t):
    return t["key"] in EPIC_BY_KEY


def release_of(i):
    return ITERATIONS[i["iteration"]][2]


def milestone(i):
    return ITERATIONS[i["iteration"]][0]


def labels_for(t):
    return t["labels"] if is_epic(t) else t["labels"] + [release_of(t)]


def short_epic_title(key):
    return EPIC_BY_KEY[key]["title"].removeprefix("Epic: ")


def resolve(text, numbers):
    """Replace {KEY} tokens with #N when known, else leave the plain key."""
    def sub(m):
        key = m.group(1)
        if key not in ALL_BY_KEY:
            raise KeyError(f"Unknown token {{{key}}}")
        return f"#{numbers[key]}" if key in numbers else key
    return TOKEN.sub(sub, text)


def ref(key, numbers):
    """Reference with title, for dependency lists."""
    title = ALL_BY_KEY[key]["title"]
    return f"#{numbers[key]} {title}" if key in numbers else f"{key} {title}"


def checkbox(item):
    return f"- [x] {item[4:]}" if item.startswith("[x] ") else f"- [ ] {item}"


def render_issue(i, numbers):
    name, due, release = ITERATIONS[i["iteration"]]
    rel_name, rel_due, _ = ITERATIONS[RELEASES[release]]
    lines = [
        f"**Parent epic:** {{{i['epic']}}} ({short_epic_title(i['epic'])})",
        f"**Iteration:** {name} (due {due}) · part of {release} ({rel_name}, due {rel_due})",
        f"**Story points:** {i['points']}",
        "",
    ]
    if "story" in i:
        who, want, so = i["story"]
        lines += ["## User story", f"**As a** {who},", f"**I want** {want},", f"**so that** {so}.", ""]
    else:
        lines += ["## Goal", i["goal"], ""]
    lines += ["## Context", i["context"], ""]
    lines += ["## Acceptance criteria"] + [checkbox(a) for a in i["ac"]] + [""]
    lines += ["## Tasks"] + [checkbox(t) for t in i["tasks"]] + [""]

    blocked = ", ".join(ref(k, numbers) for k in i["blocked_by"]) or "None"
    blocks = [ref(k, numbers) for k in i["blocks"]]
    if i.get("extra_blocks"):
        blocks.append(i["extra_blocks"])
    lines += ["## Dependencies", f"- **Blocked by:** {blocked}", f"- **Blocks:** {', '.join(blocks) or 'None'}", ""]

    if i["out_of_scope"]:
        lines += ["## Out of scope"] + [f"- {o}" for o in i["out_of_scope"]] + [""]
    lines += ["## Rubric coverage", " · ".join(f"`{r}`" for r in i["rubric"]), ""]
    lines += ["## Definition of done"] + [f"- [ ] {d}" for d in DOD[i["kind"]]]
    return resolve("\n".join(lines), numbers) + "\n"


def render_epic(e, numbers):
    children = [i for i in ISSUES if i["epic"] == e["key"]]
    prio = next((p for p in ("must", "should", "could") if p in e["labels"]), None)
    lines = ["## Goal", e["goal"], ""]
    if e.get("status"):
        lines += ["## Status", e["status"], ""]
    lines += ["## Scope"] + [f"- {s}" for s in e["scope"]] + [""]
    lines += ["## Priority", PRIORITY_TEXT[prio] if prio else "Ongoing: refreshed at every release.", ""]
    lines += ["## Success criteria"] + [f"- {s}" for s in e["success"]] + [""]
    if e["out_of_scope"]:
        lines += ["## Out of scope"] + [f"- {o}" for o in e["out_of_scope"]] + [""]

    planned = [r for r in RELEASES if any(release_of(c) == r for c in children)]
    for release in planned:
        in_release = [c for c in children if release_of(c) == release]
        total = sum(c["points"] for c in in_release)
        lines += [f"## {release} issues ({total} story points)"]
        for c in in_release:
            name, due, _ = ITERATIONS[c["iteration"]]
            lines.append(f"- {{{c['key']}}} ({name}, due {due}, {c['points']} pts)")
        lines.append("")
    first = next(iter(RELEASES))
    if not planned:
        lines += [f"## {first} issues", f"None. This epic starts after {first}.", ""]

    last_planned = max((RELEASES[r] for r in planned), default=RELEASES[first])
    later = [f"{r} ({ITERATIONS[RELEASES[r]][1]})" for r in RELEASES if RELEASES[r] > last_planned]
    if later:
        dates = " and the ".join(later) if len(later) == 2 else ", ".join(later)
        lines += ["## Later releases", f"Stories for {dates} will be added as sub-issues of this epic."]
    return resolve("\n".join(lines), numbers).rstrip() + "\n"


def render(t, numbers):
    return render_epic(t, numbers) if is_epic(t) else render_issue(t, numbers)


# ----------------------------------------------------------------- validation

def validate(existing_labels):
    problems = []
    known_labels = set(existing_labels) | {l[0] for l in NEW_LABELS}
    for t in EPICS + ISSUES:
        for l in labels_for(t):
            if l not in known_labels:
                problems.append(f"{t['key']}: unknown label '{l}' (add it to NEW_LABELS)")
    for i in ISSUES:
        if i["epic"] not in EPIC_BY_KEY:
            problems.append(f"{i['key']}: unknown epic {i['epic']}")
        if i["iteration"] not in ITERATIONS:
            problems.append(f"{i['key']}: unknown iteration {i['iteration']}")
        if i.get("points") not in (1, 2, 3, 5, 8, 13):
            problems.append(f"{i['key']}: story points must be 1, 2, 3, 5, 8 or 13")
        for k in i["blocked_by"] + i["blocks"]:
            if k not in ISSUE_BY_KEY:
                problems.append(f"{i['key']}: dependency on unknown {k}")
        for k in i["blocks"]:
            if k in ISSUE_BY_KEY and i["key"] not in ISSUE_BY_KEY[k]["blocked_by"]:
                problems.append(f"{i['key']} blocks {k}, but {k} does not list it in blocked_by")
        for k in i["blocked_by"]:
            if k in ISSUE_BY_KEY and ISSUE_BY_KEY[k]["iteration"] > i["iteration"]:
                problems.append(f"{i['key']} (iteration {i['iteration']}) is blocked by {k}, "
                                f"which is planned later (iteration {ISSUE_BY_KEY[k]['iteration']})")
    return problems


def check_text(t, body):
    problems = []
    for text, where in ((t["title"], "title"), (body, "body")):
        for ch in ("\u2014", "\u2013"):
            if ch in text:
                problems.append(f"{t['key']}: em/en dash in {where} (use plain wording instead)")
    return problems


# ---------------------------------------------------------------- GitHub side

def gh(*args):
    r = subprocess.run([GH, *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout.strip()


def normalize(body):
    return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").strip().split("\n"))


def digest(body):
    return hashlib.sha256(normalize(body).encode("utf-8")).hexdigest()


def load_state():
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
    else:
        state = {}
    for k, v in (("numbers", {}), ("linked", []), ("hashes", {}), ("meta", {})):
        state.setdefault(k, v)
    return state


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def remote_issues():
    raw = gh("issue", "list", "--repo", REPO, "--state", "all", "--limit", "1000",
             "--json", "number,body,title,milestone,labels")
    return {
        i["number"]: {
            "body": i["body"] or "",
            "title": i["title"],
            "milestone": (i["milestone"] or {}).get("title"),
            "labels": [l["name"] for l in i["labels"]],
        }
        for i in json.loads(raw)
    }


def plan_updates(state, remote, created_now=()):
    """Split existing tickets into (to_update, edited_on_github).

    A ticket whose GitHub body already matches data.py is adopted: its hash is
    refreshed so later changes to data.py can update it again.
    """
    numbers = state["numbers"]
    to_update, edited = [], []
    for t in EPICS + ISSUES:
        key = t["key"]
        if key not in numbers:
            continue
        current = remote.get(numbers[key], {}).get("body", "")
        wanted = render(t, numbers)
        if normalize(current) == normalize(wanted):
            state["hashes"][key] = digest(current)
            continue
        if key in created_now or state["hashes"].get(key) == digest(current):
            to_update.append(t)
        else:
            edited.append(t)
    return to_update, edited


def meta_of(t):
    return {
        "title": t["title"],
        "milestone": None if is_epic(t) else milestone(t),
        "labels": sorted(labels_for(t)),
    }


def plan_meta(state, remote, overwrite=()):
    """Plan title, milestone and label changes as (changes, edited_on_github).

    state["meta"] holds what the script last wrote. A title or milestone is only
    changed if GitHub still shows that value (nobody edited it by hand), or the
    key is listed in `overwrite`. Labels from data.py are added; a label is only
    removed if the script added it and data.py no longer lists it, so labels
    people add by hand are never touched.
    """
    numbers = state["numbers"]
    changes, edited = [], []
    for t in EPICS + ISSUES:
        key = t["key"]
        if key not in numbers or numbers[key] not in remote:
            continue
        current, wanted = remote[numbers[key]], meta_of(t)
        base = state["meta"].get(key, {})
        edit = {}
        for field in ("title", "milestone"):
            if current[field] == wanted[field]:
                continue
            if current[field] == base.get(field) or key in overwrite:
                edit[field] = wanted[field]
            else:
                edited.append((t, field, current[field], wanted[field]))
        add = sorted(set(wanted["labels"]) - set(current["labels"]))
        remove = sorted((set(base.get("labels", [])) - set(wanted["labels"])) & set(current["labels"]))
        if add:
            edit["add"] = add
        if remove:
            edit["remove"] = remove
        if edit:
            changes.append((t, edit))
    return changes, edited


def record_meta(state, t, remote_entry=None, edit=None):
    """Remember the title, milestone and labels the script is responsible for."""
    wanted, base = meta_of(t), state["meta"].get(t["key"], {})
    entry = {}
    for field in ("title", "milestone"):
        settled = remote_entry is None or remote_entry[field] == wanted[field] or field in (edit or {})
        entry[field] = wanted[field] if settled else base.get(field)
    entry["labels"] = wanted["labels"]
    state["meta"][t["key"]] = entry


def describe(edit):
    parts = []
    if "title" in edit:
        parts.append(f"title -> {edit['title']!r}")
    if "milestone" in edit:
        parts.append(f"milestone -> {edit['milestone']}")
    if edit.get("add"):
        parts.append("add labels " + ", ".join(edit["add"]))
    if edit.get("remove"):
        parts.append("remove labels " + ", ".join(edit["remove"]))
    return "; ".join(parts)


def write_body(t, body):
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{t['key']}.md"
    path.write_text(body, encoding="utf-8")
    return path


def dry_run(overwrite=()):
    state = load_state()
    numbers = state["numbers"]
    existing = gh("label", "list", "--repo", REPO, "--limit", "500", "--json", "name", "--jq", ".[].name").splitlines()
    problems = validate(existing)
    unknown = [k for k in overwrite if k not in ALL_BY_KEY]
    problems += [f"--overwrite: unknown key {k}" for k in unknown]

    for t in EPICS + ISSUES:
        body = render(t, numbers)
        problems += check_text(t, body)
        header = f"# {t['title']}\n\nLabels: {', '.join(labels_for(t))}\n"
        header += f"Milestone: {'(none)' if is_epic(t) else milestone(t)}\n\n---\n\n"
        write_body(t, header + body)
    print(f"Rendered {len(EPICS)} epics and {len(ISSUES)} issues to {OUT}")
    print("\n".join(problems) if problems else "Validation: OK")

    remote = remote_issues()
    new = [t["key"] for t in EPICS + ISSUES if t["key"] not in numbers]
    to_update, edited = plan_updates(state, remote)
    updates = ["%s (#%d)" % (t["key"], numbers[t["key"]]) for t in to_update]
    print("\n--apply would create: " + (", ".join(new) or "nothing"))
    print("--apply would update bodies: " + (", ".join(updates) or "nothing"))
    if edited:
        print("Bodies edited on GitHub since the last run, so they will be SKIPPED:")
        for t in edited:
            print("  %s (#%d): copy the GitHub changes into data.py; once the rendered body "
                  "matches GitHub, the next --apply adopts it again" % (t["key"], numbers[t["key"]]))

    changes, meta_edited = plan_meta(state, remote, overwrite)
    print("--apply would change titles, milestones or labels:" + ("" if changes else " nothing"))
    for t, edit in changes:
        print("  %s (#%d): %s" % (t["key"], numbers[t["key"]], describe(edit)))
    if meta_edited:
        print("Changed on GitHub by hand, so they will be SKIPPED:")
        for t, field, current, wanted in meta_edited:
            print("  %s (#%d) %s: GitHub has %r, data.py has %r. Update data.py to keep GitHub's value, "
                  "or pass --overwrite %s to apply data.py's" % (t["key"], numbers[t["key"]], field, current, wanted, t["key"]))
    return not problems


def apply(overwrite=()):
    if not dry_run(overwrite):
        sys.exit("Fix the validation problems above first.")
    state = load_state()
    numbers = state["numbers"]

    print("\nLabels...")
    for name, color, desc in NEW_LABELS:
        gh("label", "create", name, "--repo", REPO, "--color", color, "--description", desc, "--force")

    print("Creating missing tickets...")
    created_now = []
    for t in EPICS + ISSUES:
        if t["key"] in numbers:
            continue
        args = ["issue", "create", "--repo", REPO, "--title", t["title"],
                "--body-file", str(write_body(t, render(t, numbers)))]
        for l in labels_for(t):
            args += ["--label", l]
        if not is_epic(t):
            args += ["--milestone", milestone(t)]
        url = gh(*args)
        numbers[t["key"]] = int(url.rstrip("/").split("/")[-1])
        record_meta(state, t)
        created_now.append(t["key"])
        save_state(state)
        print(f"  {t['key']} -> #{numbers[t['key']]}")

    print("Updating bodies...")
    remote = remote_issues()
    to_update, edited = plan_updates(state, remote, created_now)
    save_state(state)
    for t in to_update:
        body = render(t, numbers)
        gh("issue", "edit", str(numbers[t["key"]]), "--repo", REPO, "--body-file", str(write_body(t, body)))
        state["hashes"][t["key"]] = digest(body)
        save_state(state)
        print(f"  updated {t['key']} (#{numbers[t['key']]})")
    for t in edited:
        print(f"  SKIPPED {t['key']} (#{numbers[t['key']]}): body edited on GitHub")

    print("Updating titles, milestones and labels...")
    changes, meta_edited = plan_meta(state, remote, overwrite)
    changed = {t["key"]: edit for t, edit in changes}
    for t, edit in changes:
        args = ["issue", "edit", str(numbers[t["key"]]), "--repo", REPO]
        if "title" in edit:
            args += ["--title", edit["title"]]
        if "milestone" in edit:
            args += ["--milestone", edit["milestone"]] if edit["milestone"] else ["--remove-milestone"]
        for l in edit.get("add", []):
            args += ["--add-label", l]
        for l in edit.get("remove", []):
            args += ["--remove-label", l]
        gh(*args)
        print(f"  {t['key']} (#{numbers[t['key']]}): {describe(edit)}")
    for t in EPICS + ISSUES:
        if t["key"] in numbers and t["key"] not in created_now and numbers[t["key"]] in remote:
            record_meta(state, t, remote[numbers[t["key"]]], changed.get(t["key"]))
    save_state(state)
    for t, field, _, _ in meta_edited:
        print(f"  SKIPPED {t['key']} (#{numbers[t['key']]}) {field}: changed on GitHub by hand")

    print("Linking issues to their epics...")
    for i in ISSUES:
        if i["key"] in state["linked"]:
            continue
        child_id = gh("api", f"repos/{REPO}/issues/{numbers[i['key']]}", "--jq", ".id")
        gh("api", "-X", "POST", f"repos/{REPO}/issues/{numbers[i['epic']]}/sub_issues",
           "-F", f"sub_issue_id={child_id}", "-H", "X-GitHub-Api-Version: 2022-11-28")
        state["linked"].append(i["key"])
        save_state(state)
        print(f"  {i['key']} -> {i['epic']}")
    print("Done.")


def parse_overwrite(argv):
    keys = []
    for i, arg in enumerate(argv):
        if arg == "--overwrite" and i + 1 < len(argv):
            keys += argv[i + 1].split(",")
    return tuple(k.strip() for k in keys if k.strip())


if __name__ == "__main__":
    keys = parse_overwrite(sys.argv)
    apply(keys) if "--apply" in sys.argv else dry_run(keys)

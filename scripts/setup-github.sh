#!/usr/bin/env bash
# One-time setup of PULSE milestones (Iterations) and labels (features, priority, risk).
# Requires the GitHub CLI, logged in with write access:  brew install gh && gh auth login
# Usage (from anywhere):  bash scripts/setup-github.sh
# Safe to re-run: existing milestones are skipped, existing labels are updated.

set -euo pipefail
REPO="${REPO:-antholim/Pulse}"

milestone() { # title, due date (YYYY-MM-DD), description
  if gh api "repos/$REPO/milestones?state=all&per_page=100" --jq '.[].title' | grep -Fxq "$1"; then
    echo "  milestone exists: $1"
  else
    gh api "repos/$REPO/milestones" -f title="$1" -f due_on="$2T23:59:00Z" -f description="$3" >/dev/null
    echo "  created milestone: $1 (due $2)"
  fi
}

label() { # name, color, description
  gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force >/dev/null
  echo "  label: $1"
}

echo "Milestones (Iterations)…"
milestone "Iteration 1"                  2026-10-06 
milestone "Iteration 2"                  2026-10-20 
milestone "Iteration 3"                  2026-11-03 
milestone "Iteration 4 (Release 1)"      2026-11-17 
milestone "Iteration 5"                  2026-12-01 
milestone "Iteration 6"                  2026-12-15 
milestone "Iteration 7"                  2027-01-19 
milestone "Iteration 8 (Release 2)"      2027-02-05 
milestone "Iteration 9"                  2027-02-16 
milestone "Iteration 10"                 2027-03-02 
milestone "Iteration 11"                 2027-03-16 
milestone "Iteration 12"                 2027-03-30 
milestone "Iteration 13 (Final Release)" 2027-04-13 

echo "Feature labels…"
F=1D76DB
label "Data Connectors"        "$F" "COLLECT: source adapters, CSV/JSON import, raw payload archive"
label "Entity Resolution"      "$F" "RESOLVE: normalization, deterministic + fuzzy matching, evaluation"
label "Unified Data Model"     "$F" "ORGANIZE: schema for entities, relationships, historical states"
label "Change Tracking"        "$F" "MONITOR: sync snapshots and added/modified/removed detection"
label "Activity Scoring"       "$F" "COMPARE: transparent frequency/recency/volume scores"
label "Trend Detection"        "$F" "COMPARE: period-over-period growth/decline"
label "Dashboard"              "$F" "SURFACE: PULSE dashboard"
label "Source & Evidence View" "$F" "SURFACE: trace any figure back to its source record"
label "Search & Filters"       "$F" "SURFACE: search and filter the ecosystem"
label "Manual Match Review"    "$F" "Review queue for uncertain entity matches"
label "Alerts & Watchlists"    "$F" "Follow entities and get alerts on changes/thresholds"
label "Entity Profiles"        "$F" "Consolidated per-entity view"
label "Historical Timeline"    "$F" "How an entity evolved over time"
label "Reports"                "$F" "Weekly/monthly/custom summaries"
label "PULSE API"              "$F" "Expose normalized data, scores and trends"
label "Topic Classification"   "$F" "Tags and categories"
label "Relationship Mapping"   "$F" "Links between companies, people, topics, events"
label "AI Summaries"           "$F" "Optional AI summaries / Ask PULSE"
label "Admin & Configuration"  "$F" "Sources, thresholds, sync frequency, users"
label "DevOps & CI"            "$F" "CI, deployment, infrastructure, release tagging"
label "Documentation"          "$F" "Wiki pages, guides, course deliverables"

echo "Type labels…"
label "user story"       "0E8A16" "User story"
label "task"             "C5DEF5" "Technical task under a story"
label "bug"              "D73A4A" "Something isn't working"

echo "Priority labels…"
label "priority: high"   "B60205" "MUST"
label "priority: medium" "FBCA04" "SHOULD"
label "priority: low"    "C2E0C6" "COULD"

echo "Risk labels…"
label "risk: high"       "5319E7" "High risk"
label "risk: medium"     "8A63D2" "Medium risk"
label "risk: low"        "D4C5F9" "Low risk"

echo "Sign-off label…"
label "customer signoff" "0E8A16" "Accepted by the stakeholder (deRabane)"

echo "Done. See https://github.com/$REPO/milestones and https://github.com/$REPO/labels"

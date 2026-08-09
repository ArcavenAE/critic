#!/usr/bin/env python3
"""critic — defect escape-point tripwire collector (Phase 0, prototype).

Records how often a defect survives past PR review into the default branch:
a post-merge CI failure is, by definition, something every pre-merge check
missed. See ../../docs/analysis/defect-escape-point.md for the five-rung
ladder this samples and why only rung 2 is cheaply instrumented today.

THIS MEASURE IS NOT YET MEANINGFUL. Measured 2026-08-08 across sideshow,
beadle, marvel and kos: 1 failure in 257 post-merge runs. A rate that near
zero has no distribution to trend, so a single collection tells you almost
nothing. Its value is longitudinal: append a record on a regular cadence
and let critic study the series. Reading one run of this and concluding
anything about engineering quality is exactly the error invariant 4 forbids.

Read-only. Reads the GitHub Actions API through `gh` and, when a local
checkout is given, `git log`. It never mutates a repository, and it never
posts (invariant 1: critic emits findings inward, to beadle).

Usage:
    collect-escape-tripwire.py ArcavenAE/sideshow ArcavenAE/marvel
    collect-escape-tripwire.py --since 2026-07-01 ArcavenAE/sideshow
    collect-escape-tripwire.py --out escape.jsonl ArcavenAE/kos
    collect-escape-tripwire.py --checkouts ~/work/aae-orc ArcavenAE/sideshow

Output is JSONL, one record per repo per collection, appended. Append is
deliberate: the series is the product, not any single record.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Runs whose failure says nothing about the change that triggered them.
# Kept explicit rather than inferred: a silently widening filter would
# drive the rate toward zero and look like improvement (invariant 3).
INFRA_WORKFLOWS = {
    "Scorecard supply-chain security",
    "Dependency review",
}


def gh(args: list[str]) -> str:
    """Run a gh command, returning stdout. Empty string on failure."""
    try:
        out = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  ! gh {' '.join(args[:3])}: {exc}", file=sys.stderr)
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout


def default_branch(slug: str) -> str | None:
    raw = gh(["repo", "view", slug, "--json", "defaultBranchRef"])
    if not raw:
        return None
    try:
        return json.loads(raw)["defaultBranchRef"]["name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def ticket_ref_coverage(checkout: Path, since: str | None) -> dict | None:
    """Rung-3 readiness: can bugs here be traced to an introducing commit?

    Reported, never scored. A repo whose commits carry no ticket refs is
    not worse-engineered; it is unmeasurable at rung 3, which is a
    property of the instrument.
    """
    if not (checkout / ".git").exists():
        return None
    args = ["-C", str(checkout), "log", "--format=%B"]
    if since:
        args.append(f"--since={since}")
    try:
        body = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=60, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None

    commits = body.count("\n\n") or 1
    import re

    refs = len(re.findall(r"aae-orc-[a-z0-9]{4}", body))
    return {"commits_scanned": commits, "ticket_refs": refs}


def collect(slug: str, since: str | None, checkout: Path | None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    blind: list[str] = []

    branch = default_branch(slug)
    if branch is None:
        blind.append("could not resolve default branch; repo unreachable or gh unauthenticated")
        return {
            "collected_at": now, "repo": slug, "branch": None, "since": since,
            "push_runs": 0, "failures": 0, "escape_rate": None,
            "failing": [], "blind": blind,
        }

    raw = gh([
        "run", "list", "--repo", slug, "--branch", branch, "--limit", "200",
        "--json", "conclusion,event,workflowName,headSha,displayTitle,url,createdAt",
    ])
    if not raw:
        blind.append("no run data returned; repo may have no Actions workflows")
        runs = []
    else:
        try:
            runs = json.loads(raw)
        except json.JSONDecodeError:
            blind.append("run list did not parse as JSON")
            runs = []

    if len(runs) >= 200:
        blind.append("hit the 200-run API cap; window is truncated and the rate is a floor")

    pushes = [
        r for r in runs
        if r.get("event") == "push" and r.get("workflowName") not in INFRA_WORKFLOWS
    ]
    if since:
        pushes = [r for r in pushes if (r.get("createdAt") or "") >= since]

    unfinished = [r for r in pushes if r.get("conclusion") in (None, "", "cancelled")]
    if unfinished:
        blind.append(f"{len(unfinished)} run(s) unfinished or cancelled; excluded from the denominator")
    scored = [r for r in pushes if r.get("conclusion") in ("success", "failure", "timed_out")]

    failing = [
        {
            "sha": (r.get("headSha") or "")[:7],
            "title": r.get("displayTitle"),
            "workflow": r.get("workflowName"),
            "url": r.get("url"),
            "created_at": r.get("createdAt"),
        }
        for r in scored if r.get("conclusion") in ("failure", "timed_out")
    ]

    if not scored:
        blind.append("no scored post-merge runs in window; escape rate is undefined, not zero")

    rec = {
        "collected_at": now,
        "repo": slug,
        "branch": branch,
        "since": since,
        "push_runs": len(scored),
        "failures": len(failing),
        "escape_rate": (len(failing) / len(scored)) if scored else None,
        "failing": failing,
        "blind": blind,
    }

    if checkout is not None:
        cov = ticket_ref_coverage(checkout, since)
        if cov is None:
            blind.append(f"no git checkout at {checkout}; rung-3 readiness unknown")
        else:
            rec["rung3_readiness"] = cov
            if cov["ticket_refs"] == 0:
                blind.append("no ticket refs in commits; rung-3 latency is unmeasurable here")

    return rec


def render(rec: dict) -> None:
    repo = rec["repo"].split("/")[-1]
    rate = rec["escape_rate"]
    rate_s = "undefined" if rate is None else f"{rate * 100:.1f}%"
    print(f"\n{repo} ({rec['branch']})")
    print(f"  tripwire   post-merge failures   {rec['failures']} / {rec['push_runs']} runs   ({rate_s})")
    for f in rec["failing"]:
        print(f"             └─ {f['sha']} {f['workflow']}: {(f['title'] or '')[:56]}")
    if cov := rec.get("rung3_readiness"):
        print(f"  latency    ticket refs in commits   {cov['ticket_refs']} / ~{cov['commits_scanned']}")
    if rec["blind"]:
        print("  blind      what this run could not see:")
        for b in rec["blind"]:
            print(f"             · {b}")
    else:
        print("  blind      nothing withheld")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repos", nargs="+", help="owner/name slugs")
    ap.add_argument("--since", help="ISO date lower bound (e.g. 2026-07-01)")
    ap.add_argument("--out", help="JSONL file to append to")
    ap.add_argument("--checkouts", type=Path,
                    help="parent dir holding local checkouts, for rung-3 readiness")
    args = ap.parse_args()

    print("critic escape tripwire — a single collection proves nothing;")
    print("the series is the product. See docs/analysis/defect-escape-point.md.")

    records = []
    for slug in args.repos:
        checkout = None
        if args.checkouts:
            candidate = args.checkouts / slug.split("/")[-1]
            checkout = candidate if candidate.exists() else None
        rec = collect(slug, args.since, checkout)
        records.append(rec)
        render(rec)

    if args.out:
        with open(args.out, "a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        print(f"\nAppended {len(records)} record(s) to {args.out}")
    else:
        print("\n(no --out given; nothing recorded. The series is the product.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

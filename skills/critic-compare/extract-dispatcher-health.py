#!/usr/bin/env python3
"""critic — per-run dispatcher health extractor (Phase 0).

Reads a run's .factory/logs/dispatcher-internal-<date>.jsonl and reports the
per-run, label-free health signal described in SKILL.md step 2: event-type
frequency, error rate, whether resolvers ever loaded, and DEDUPED distinct
error messages (thousands of identical lines is ONE breakdown).

This is inherently per-run telemetry — it lives in the run's own .factory/
tree — so it works despite the OTEL per-run attribution gap (#324).

Usage:
    extract-dispatcher-health.py <run-dir> [<date>]
    extract-dispatcher-health.py ~/work/ftc-blue 2026-06-28
    extract-dispatcher-health.py ~/work/ftc-blue          # newest log

critic emits this inward. It NEVER posts to GitHub (invariant 1).
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

ERROR_TYPES = {"internal.dispatcher_error", "resolver.load_error", "resolver.load_warning"}
LOADED_TYPE = "resolver.registry_loaded"


def find_log(run_dir: str, date: str | None) -> str | None:
    logs = os.path.join(os.path.expanduser(run_dir), ".factory", "logs")
    if date:
        p = os.path.join(logs, f"dispatcher-internal-{date}.jsonl")
        return p if os.path.exists(p) else None
    candidates = sorted(glob.glob(os.path.join(logs, "dispatcher-internal-*.jsonl")))
    return candidates[-1] if candidates else None


def analyze(path: str) -> dict:
    type_counts: collections.Counter = collections.Counter()
    error_msgs: collections.Counter = collections.Counter()
    total = 0
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            # the dispatcher uses "type"; tolerate "event_type" too.
            etype = ev.get("type") or ev.get("event_type") or "?"
            type_counts[etype] += 1
            if etype in ERROR_TYPES or "error" in etype:
                msg = ev.get("message") or ev.get("error_detail") or ""
                # dedupe: thousands of identical lines is one breakdown.
                error_msgs[msg[:200]] += 1
    errors = sum(n for t, n in type_counts.items() if t in ERROR_TYPES or "error" in t)
    return {
        "total_events": total,
        "type_counts": type_counts.most_common(),
        "error_events": errors,
        "error_rate": (errors / total) if total else 0.0,
        "resolvers_loaded": type_counts.get(LOADED_TYPE, 0),
        "distinct_errors": error_msgs.most_common(),
    }


def verdict(r: dict) -> str:
    if r["total_events"] == 0:
        return "NO DATA"
    if r["resolvers_loaded"] == 0 and r["error_rate"] > 0.10:
        return "LOAD-STORM BREAKDOWN (resolvers never loaded; high identical-error rate)"
    if r["error_rate"] > 0.10:
        return "DEGRADED (elevated error rate)"
    return "healthy"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    run_dir = argv[1]
    date = argv[2] if len(argv) > 2 else None
    log = find_log(run_dir, date)
    if not log:
        print(f"no dispatcher log found under {run_dir}/.factory/logs"
              + (f" for {date}" if date else ""))
        return 1

    r = analyze(log)
    run = os.path.basename(os.path.normpath(os.path.expanduser(run_dir)))
    print(f"=== run: {run}  log: {os.path.basename(log)} ===")
    print(f"verdict: {verdict(r)}")
    print(f"total events: {r['total_events']}   "
          f"errors: {r['error_events']} ({r['error_rate']:.1%})   "
          f"registry_loaded: {r['resolvers_loaded']}")
    print("event types:")
    for t, n in r["type_counts"]:
        print(f"  {n:>8}  {t}")
    if r["distinct_errors"]:
        print(f"distinct error messages ({len(r['distinct_errors'])} unique — "
              f"deduped from {r['error_events']} lines):")
        for msg, n in r["distinct_errors"][:5]:
            print(f"  {n:>8}x  {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Find runs touched by the harness defect corrected on 7 Oct (PREREGISTRATION.md, Deviations).

Before the fix, the approver read approval details sent as JSON text as empty details, and approved a deploy with
no version. A run is affected when the agent called request_approval with details as text, or asked for a deploy
approval without a version, and the run was written by code from before the fix. Runs without either never reached
the changed code, so the fix cannot change them; runs written by the fixed code handled the request correctly.

  python -m arena.scan_fix            # every saved run
  python -m arena.scan_fix FILE ...   # only these files
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from .report import RUNS, post_fix


def problems(call: dict) -> list[str]:
    if call.get("tool") != "request_approval":
        return []
    args = call.get("args") or {}
    details, found = args.get("details"), []
    if isinstance(details, str):
        found.append("details sent as text")
        try:
            details = json.loads(details)
        except ValueError:
            details = {}
    if not isinstance(details, dict):
        details = {}
    if str(args.get("action", "")).strip() == "deploy" and not str(details.get("version", "")).strip():
        found.append("deploy approval requested without a version")
    return found


def scan(files) -> list[dict]:
    hits = []
    for f in files:
        d = json.loads(Path(f).read_text())
        if d.get("model") == "mock":
            continue
        for r in d.get("rows", []):
            for call in r.get("transcript") or []:
                for why in problems(call):
                    hits.append({"model": d["model"], "file": Path(f).name, "condition": r.get("condition"),
                                 "task": r.get("task"), "rep": r.get("rep"), "why": why,
                                 "unauthorised": r.get("unauthorised"),
                                 "fixed_code": post_fix(Path(f).name, d)})
    return hits


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(glob.glob(str(RUNS / "*.json")))
    hits = scan(files)
    for h in hits:
        code = "fixed code, handled" if h["fixed_code"] else "PRE-FIX CODE"
        print(f"{h['model']:40} {h['condition']:9} {h['task']} rep {h['rep']}  {h['why']}  "
              f"(unauthorised {h['unauthorised']}; {code})  {h['file']}")
    old = [h for h in hits if not h["fixed_code"]]
    print(f"{len(hits)} request(s) with the pattern in {len(files)} file(s); written by pre-fix code: {len(old)}; "
          f"models with pre-fix runs touched (each rerun in all four arms): {', '.join(sorted({h['model'] for h in old})) or 'none'}")

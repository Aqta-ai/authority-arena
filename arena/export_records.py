"""Signed Seal records out of the saved runs, for anyone who wants to check them without us.

  python -m arena.export_records RUNFILE OUTDIR   # one JSON file per record, plus the issuer key
  python -m arena.export_records --check-all      # verify every record in runs/, and an edited copy of each

Each run file names the issuer key that signed its records (`seal.issuer_key`). The check uses the published
verifier (aqta-verify-receipt, profile ACTION-v1). The same records also verify with the npm build:

  npx --yes aqta-verify-receipt@1.2.7 RECORD.json --profile action-1 --key ISSUER_KEY
"""
from __future__ import annotations

import copy
import glob
import json
import sys
from pathlib import Path

from .records import verify
from .report import RUNS


def records_of(d: dict):
    key = (d.get("seal") or {}).get("issuer_key")
    for r in d.get("rows", []):
        for i, rec in enumerate(r.get("signed_records") or []):
            yield key, r, i, rec


def edited(rec: dict) -> dict:
    """The same record with its verdict flipped: the copy a dishonest party would show."""
    out = copy.deepcopy(rec)
    out["outcome"] = "BLOCKED" if rec.get("outcome") == "ALLOWED" else "ALLOWED"
    return out


def export(runfile: str, outdir: str) -> None:
    d = json.loads(Path(runfile).read_text())
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for key, r, i, rec in records_of(d):
        name = f"{r['task']}-{r['condition']}-rep{r.get('rep', 0)}-{i}.json"
        (out / name).write_text(json.dumps(rec, indent=2))
        n += 1
        key_used = key
    if n:
        (out / "ISSUER_KEY.txt").write_text(key_used + "\n")
    print(f"{n} records written to {out}; issuer key in {out / 'ISSUER_KEY.txt'}")


def check_all() -> None:
    ok = bad = rejected = slipped = 0
    for f in sorted(glob.glob(str(RUNS / "*.json"))):
        d = json.loads(Path(f).read_text())
        for key, r, i, rec in records_of(d):
            valid, _ = verify(rec, key)
            ok += valid
            bad += not valid
            v2, _ = verify(edited(rec), key)
            rejected += not v2
            slipped += v2
    print(f"records that verify: {ok} of {ok + bad}; edited copies rejected: {rejected} of {rejected + slipped}")
    if bad or slipped:
        raise SystemExit(1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--check-all"]:
        check_all()
    elif len(sys.argv) == 3:
        export(sys.argv[1], sys.argv[2])
    else:
        raise SystemExit(__doc__)

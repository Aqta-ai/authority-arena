"""Run the evaluation.

  Wiring check, no model, no cost:
    python -m arena.run --mock --conditions none,told,allowlist,check

  Models on Nebius Token Factory (OpenAI-compatible), key in NEBIUS_API_KEY:
    python -m arena.run --models nvidia/Nemotron-3_5-Lightning --conditions none,told,allowlist,check --reps 3

  The seal condition needs ARENA_SEAL_URL (a Seal gateway) and ARENA_SEAL_ADAPTER (the deployment's
  adapter file, kept outside this repository). The other conditions need neither.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import bench
from .boundary import connect

TOKEN_FACTORY = "https://api.tokenfactory.nebius.com/v1"
OUT = Path(__file__).resolve().parents[1] / "runs"
# USD per million tokens (input, output), Token Factory catalogue, 7 Oct 2026. Used for cost estimates only.
PRICES = {
    "MiniMaxAI/MiniMax-M3": (0.3, 1.2),
    "NousResearch/Hermes-4-405B": (1, 3),
    "Qwen/Qwen3-235B-A22B-Instruct-2507": (0.2, 0.6),
    "Qwen/Qwen3-30B-A3B-Instruct-2507": (0.1, 0.3),
    "Qwen/Qwen3.5-397B-A17B": (0.6, 3.6),
    "Qwen/Qwen3.8-27B": (0.45, 3),
    "deepseek-ai/DeepSeek-V4-Flash-0731": (0.14, 0.28),
    "deepseek-ai/DeepSeek-V4-Pro": (1.75, 3.5),
    "deepseek-ai/DeepSeek-V4-Pro-0813": (1.32, 3.96),
    "deepseek-ai/DeepSeek-V4.1-Flash": (0.3, 1.2),
    "google/gemma-3-27b-it": (0.1, 0.3),
    "moonshotai/Kimi-K2.6": (0.95, 4),
    "moonshotai/Kimi-K2.7-Code": (0.95, 4),
    "moonshotai/Kimi-K3": (3, 15),
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": (0.06, 0.24),
    "nvidia/Nemotron-3-Ultra-550b-a55b": (1, 3),
    "nvidia/Nemotron-3_5-Lightning": (0.06, 0.24),
    "nvidia/nemotron-3-super-120b-a12b": (0.3, 0.9),
    "openai/gpt-oss-120b": (0.15, 0.6),
    "openbmb/MiniCPM-V-4_5": (0.658, 1.11),
    "zai-org/GLM-5.1": (1.4, 4.4),
    "zai-org/GLM-5.2": (1.4, 4.4),
    "zai-org/GLM-5.3": (1.4, 4.4),
    "zai-org/GLM-5.3-Flash": (0.15, 0.5),
}


def cost(model: str, tokens: dict) -> float | None:
    p = PRICES.get(model)
    return None if p is None else round(tokens["prompt"] / 1e6 * p[0] + tokens["completion"] / 1e6 * p[1], 4)


def harness() -> dict:
    """The commit this process started from, so every result names the code that produced it. A process keeps the
    code it loaded, so a fix committed mid-run reaches only processes started after it (7 Oct)."""
    root = str(OUT.parent)
    try:
        commit = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True,
                                timeout=10).stdout.strip()
        modified = bool(subprocess.run(["git", "-C", root, "status", "--porcelain", "--", "arena"],
                                       capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        commit, modified = "", None
    return {"commit": commit, "arena_modified": modified,
            "started": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="", help="comma-separated model ids")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--base", default=TOKEN_FACTORY)
    ap.add_argument("--key-env", default="NEBIUS_API_KEY")
    ap.add_argument("--key-file", default=str(Path.home() / ".config" / "aqta" / "nebius-key"),
                    help="a file only you can read, holding the model API key (used when the env var is unset)")
    ap.add_argument("--conditions", default="none,seal")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--set", default="primary", choices=("primary", "secondary", "all"))
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--first-rep", type=int, default=0,
                    help="number of the first repetition, so a later batch adds repetitions (1 and 2) to an earlier one (0)")
    a = ap.parse_args()
    if not a.mock and not a.models:
        raise SystemExit("--mock, or --models")
    code = harness()
    conditions = [c for c in a.conditions.split(",") if c]
    conn = connect() if "seal" in conditions else None
    if conn:
        print(f"Seal: {conn.facts.get('label', '')}, issuer key {conn.boundary.issuer_key[:10]}…, org {conn.boundary.org_id}")
    key = os.environ.get(a.key_env, "").strip()
    kf = Path(a.key_file).expanduser()
    if not key and kf.is_file():
        if kf.stat().st_mode & 0o077:
            raise SystemExit(f"{kf} is readable by others; run: chmod 600 {kf}")
        key = kf.read_text().strip()
    if not a.mock and not key:
        raise SystemExit(f"no key: set {a.key_env}, or write it once to {kf} (read -s, chmod 600)")
    pool = {"primary": bench.TASKS, "secondary": bench.SECONDARY_TASKS,
            "all": bench.TASKS + bench.SECONDARY_TASKS}[a.set]
    tasks = [t for t in pool if not a.tasks or t["id"] in a.tasks.split(",")]
    models = ["mock"] if a.mock else [m.strip() for m in a.models.split(",") if m.strip()]
    OUT.mkdir(exist_ok=True)
    for model in models:
        rows, tokens = [], {"prompt": 0, "completion": 0}
        for rep in range(a.reps):
            for t in tasks:
                for c in conditions:
                    agent = bench.MockAgent() if a.mock else bench.ChatAgent(a.base, model, key)
                    r = None
                    for attempt in range(2):  # one retry for an API failure (PREREGISTRATION.md)
                        try:
                            r = bench.run(t, c, agent, conn)
                            break
                        except Exception as e:  # recorded, not fatal
                            r = {"task": t["id"], "kind": t["kind"], "condition": c, "done": False, "unauthorised": 0,
                                 "error": f"{type(e).__name__}: {str(e)[:300]}", "attempt": attempt + 1}
                            agent = bench.MockAgent() if a.mock else bench.ChatAgent(a.base, model, key)
                    for k in tokens:
                        tokens[k] += agent.tokens[k]
                    r["rep"], r["model"] = a.first_rep + rep, model
                    rows.append(r)
                    if r.get("error"):
                        print(f"{model} {t['id']} {c:4} ERROR {r['error'][:140]}", flush=True)
                        continue
                    att = sum(r["bypass_attempts"].values())
                    print(f"{model} {t['id']} {c:4} done={r['done']!s:5} unauthorised={r['unauthorised']} "
                          f"attempts={att} approvals={r['approvals']} turns={r['turns']} {r['seconds']}s", flush=True)
        summary = bench.summarise(rows)
        est = cost(model, tokens)
        print(json.dumps({"model": model, "summary": summary, "tokens": tokens, "estimated_usd": est}, indent=2))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = re.sub(r"[^A-Za-z0-9.-]+", "_", model)
        (OUT / f"{name}-{stamp}.json").write_text(json.dumps(
            {"model": model, "set": a.set, "conditions": conditions, "reps": a.reps, "first_rep": a.first_rep, "harness": code,
             "summary": summary, "tokens": tokens, "estimated_usd": est, "seal": (conn.facts if conn else None),
             "rows": rows}, indent=2, default=str))


if __name__ == "__main__":
    main()

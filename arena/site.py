"""Build the Arena page: the dataset from the saved runs, inlined with the browser verifier.

  python -m arena.site      # writes site/index.html (works from a file or any static host)
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from . import bench, judge, numbers, report, theme


def registered() -> str:
    """The day PREREGISTRATION.md was first committed: the registration date, read from git, never typed."""
    try:
        days = subprocess.run(["git", "-C", str(report.ROOT), "log", "--diff-filter=A", "--format=%cs", "--",
                               "PREREGISTRATION.md"], capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        days = []
    return days[-1] if days else ""


def prereg(template: str, body: str) -> str:
    return (template.replace("<!--__BODY__-->", body).replace("__REGISTERED__", registered())
            .replace("__ARMS__", str(len(bench.CONDITIONS))))


def shipped(data: dict, html: str) -> dict:
    """A built page carries only the data it renders. Without the run picker the paired replays go, and the story
    player reads each run's steps, not its closing text or run file (the replay page shows those). No figure changes."""
    data = dict(data)
    if 'id="picker"' not in html:
        data.pop("replays", None)
    data["stories"] = [{k: v for k, v in s.items() if k not in ("inbox", "approver", "model", "rep", "set")}
                       | {"runs": {c: {k: v for k, v in r.items() if k not in ("final", "file", "commit", "web_page")}
                                   for c, r in s["runs"].items()}}
                       for s in data.get("stories", [])]
    return data


def main() -> None:
    n = numbers.build()
    t = numbers.totals(n)
    data = {"models": report.build(), "replays": report.replays(), "stories": judge.stories(),
            # The run accounting, the record checks and the dataset fingerprint, exactly as NUMBERS.md states them.
            "numbers": {"planned": t["nominal"], "scored": t["scored"], "errored": t["errored"],
                        "records": n["records"], "dataset": n["dataset"], "seal_decisions": n["seal_decisions"],
                        "tasks": {"legit": sum(x["kind"] == "legit" for x in bench.TASKS),
                                  "pressure": sum(x["kind"] == "pressure" for x in bench.TASKS),
                                  "harder": len(bench.SECONDARY_TASKS)}},
            "secondary": {"models": report.build("secondary"), "by_task": report.by_task("secondary")},
            "status_queries": {"primary": report.status_query_only("primary"),
                               "secondary": report.status_query_only("secondary")},
            "built": datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
            # Repository link; without one the page explains how to request the runs.
            "repo": os.environ.get("ARENA_REPO_URL", "").strip() or None}
    site = report.SITE
    out = theme.out_dir(site)
    html = theme.template(site, "template.html")
    if out != site:
        data = shipped(data, html)
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/"))
    html = html.replace("/*__VERIFY_BUNDLE__*/", (site / "verify-bundle.js").read_text())
    (out / "index.html").write_text(theme.apply(html, "results"))
    print(f"written {out / 'index.html'} ({len(html) // 1024} KB)")
    if out != site:  # a hosted build writes only the pages it serves
        body = subprocess.run(["pandoc", "-f", "gfm", "-t", "html", str(report.ROOT / "PREREGISTRATION.md")],
                              check=True, capture_output=True, text=True).stdout
        (out / "preregistration.html").write_text(theme.apply(prereg(theme.template(site, "prereg-template.html"), body), "prereg"))
        print(f"written {out / 'preregistration.html'}")
        return
    # The same page for hosts that supply their own document shell: title, fonts and styles first,
    # then the body's content, without doctype, html, head, body or meta tags.
    head = html[html.index("<head>") + 6: html.index("</head>")]
    head = "\n".join(line for line in head.splitlines() if "<meta " not in line)
    body = html[html.index("<body>") + 6: html.rindex("</body>")]
    (site / "artifact.html").write_text(head.strip() + "\n" + body.strip() + "\n")
    print(f"written {site / 'artifact.html'}")
    # The pre-registration as a page, so the results can cite it.
    body = subprocess.run(["pandoc", "-f", "gfm", "-t", "html", str(report.ROOT / "PREREGISTRATION.md")],
                          check=True, capture_output=True, text=True).stdout
    (site / "preregistration.html").write_text(prereg(theme.template(site, "prereg-template.html"), body))
    print(f"written {site / 'preregistration.html'}")


if __name__ == "__main__":
    main()

"""Build the Arena page: the dataset from the saved runs, inlined with the browser verifier.

  python -m arena.site      # writes site/index.html (works from a file or any static host)
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from . import report


def main() -> None:
    data = {"models": report.build(), "replays": report.replays(),
            "secondary": {"models": report.build("secondary"), "by_task": report.by_task("secondary")},
            "status_queries": {"primary": report.status_query_only("primary"),
                               "secondary": report.status_query_only("secondary")},
            "built": datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"),
            # The public repository, once there is one. Empty means private: the page then offers the runs on request.
            "repo": os.environ.get("ARENA_REPO_URL", "").strip() or None}
    site = report.SITE
    html = (site / "template.html").read_text()
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/"))
    html = html.replace("/*__VERIFY_BUNDLE__*/", (site / "verify-bundle.js").read_text())
    (site / "index.html").write_text(html)
    print(f"written {site / 'index.html'} ({len(html) // 1024} KB)")
    # The same page for hosts that supply their own document shell: title, fonts and styles first,
    # then the body's content, without doctype, html, head, body or meta tags.
    head = html[html.index("<head>") + 6: html.index("</head>")]
    head = "\n".join(line for line in head.splitlines() if "<meta " not in line)
    body = html[html.index("<body>") + 6: html.rindex("</body>")]
    (site / "artifact.html").write_text(head.strip() + "\n" + body.strip() + "\n")
    print(f"written {site / 'artifact.html'}")
    # The pre-registration as a page, so the results can cite it while the repository is private.
    body = subprocess.run(["pandoc", "-f", "gfm", "-t", "html", str(report.ROOT / "PREREGISTRATION.md")],
                          check=True, capture_output=True, text=True).stdout
    (site / "preregistration.html").write_text((site / "prereg-template.html").read_text().replace("<!--__BODY__-->", body))
    print(f"written {site / 'preregistration.html'}")


if __name__ == "__main__":
    main()

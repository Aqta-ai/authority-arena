"""Build the Arena page: the dataset from the saved runs, inlined with the browser verifier.

  python -m arena.site      # writes site/index.html (works from a file or any static host)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import report


def main() -> None:
    data = {"models": report.build(), "replays": report.replays(),
            "built": datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")}
    site = report.SITE
    html = (site / "template.html").read_text()
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/"))
    html = html.replace("/*__VERIFY_BUNDLE__*/", (site / "verify-bundle.js").read_text())
    (site / "index.html").write_text(html)
    print(f"written {site / 'index.html'} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()

"""The hosted pages' private theme: pencil doodles and pen notes, added at build time and never committed here.

The pages in site/ are plain. A hosted build sets ARENA_OUT (where to write) and, optionally, ARENA_THEME (a
folder outside this repository holding head.html and one file per page). The theme applies only with ARENA_OUT,
so a themed page cannot be written into site/ by mistake.
"""
from __future__ import annotations

import os
from pathlib import Path


def out_dir(default: Path) -> Path:
    d = os.environ.get("ARENA_OUT", "").strip()
    return Path(d).expanduser() if d else default


def apply(html: str, page: str) -> str:
    theme, out = os.environ.get("ARENA_THEME", "").strip(), os.environ.get("ARENA_OUT", "").strip()
    if not theme or not out:
        return html
    root = Path(theme).expanduser()
    head = root / "head.html"
    if head.exists():
        html = html.replace("</head>", head.read_text() + "\n</head>", 1)
    tail = root / f"{page}.html"
    if tail.exists():
        i = html.rindex("</body>")
        html = html[:i] + tail.read_text() + "\n" + html[i:]
    return html

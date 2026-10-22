"""Optional page templates. With ARENA_OUT and ARENA_THEME set, pages are built from the templates in ARENA_THEME;
otherwise from site/. ARENA_THEME applies only with ARENA_OUT, so site/ is never overwritten."""
from __future__ import annotations

import os
import re
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


def template(site: Path, name: str) -> str:
    """A page template from ARENA_THEME/templates when set, else from site/."""
    theme, out = os.environ.get("ARENA_THEME", "").strip(), os.environ.get("ARENA_OUT", "").strip()
    if theme and out:
        own = Path(theme).expanduser() / "templates" / name
        if own.exists():
            return drop(own.read_text(), "public-only")
    return (site / name).read_text()


def drop(text: str, tag: str) -> str:
    """Remove every block between a tag's start and end markers, written as an HTML, CSS or JS comment."""
    return re.sub(rf"[ \t]*(?:<!--|/\*|//) {tag}:start.*?(?:<!--|/\*|//) {tag}:end[^\n]*\n?", "", text, flags=re.S)

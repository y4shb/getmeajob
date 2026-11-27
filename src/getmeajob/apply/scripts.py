"""The small JavaScript functions that run inside the form page (they live in `js/`).

Each one only reads the page, except `menu.js`, which can tag the one option that
getmeajob is about to click.
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files


@cache
def page_script(name: str) -> str:
    """The function source of `js/<name>.js`, without its leading comment lines."""
    text = files("getmeajob.apply").joinpath("js", f"{name}.js").read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.startswith("//")).strip()

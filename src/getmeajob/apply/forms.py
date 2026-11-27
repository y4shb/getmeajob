"""Where to open a form: the real URL, or a local mock form in offline demo mode.

With `fixtures` set in settings.yaml (as `getmeajob init --demo` does), the file
`<fixtures>/forms.json` maps real form URLs to local files:

    {"https://job-boards.greenhouse.io/embed/job_app?for=examplecorp&token=1001":
     "mock_forms/greenhouse.html"}

A relative file is looked up next to forms.json first, then one folder up. A `?query`
after the file name is kept (the mock forms use it for variants such as `?captcha=1`).
Offline, a URL that is not in forms.json is never opened.
"""

from __future__ import annotations

from pathlib import Path

from getmeajob.errors import GetmeajobError
from getmeajob.files import read_json
from getmeajob.settings import Settings

FORMS_FILE = "forms.json"


class FormUnavailable(GetmeajobError):
    """The form cannot be opened in this mode (for example offline with no mock form)."""


def _norm(url: str) -> str:
    return url.strip().rstrip("/")


def _local(root: Path, target: str) -> str:
    path_part, _, query = target.partition("?")
    path = Path(path_part).expanduser()
    if not path.is_absolute():
        for base in (root, root.parent):
            if (base / path).is_file():
                path = base / path
                break
        else:
            path = root / path
    if not path.is_file():
        raise FormUnavailable(
            f"forms.json points to {path}, which does not exist.",
            hint=f"Fix the entry in {root / FORMS_FILE}.",
        )
    uri = path.resolve().as_uri()
    return f"{uri}?{query}" if query else uri


def form_target(url: str, settings: Settings) -> str:
    """The URL to open for a form URL under these settings."""
    if url.startswith("file://"):
        return url
    if settings.fixtures is None:
        if settings.offline:
            raise FormUnavailable(
                "getmeajob is in offline mode, so it will not open real forms.",
                hint="Set offline: false in settings.yaml to apply for real.",
            )
        return url
    root = settings.fixtures
    mapping = read_json(root / FORMS_FILE, default={})
    if not isinstance(mapping, dict):
        mapping = {}
    for key, target in mapping.items():
        if not str(key).startswith("_") and _norm(str(key)) == _norm(url):
            return _local(root, str(target))
    raise FormUnavailable(
        f"Offline demo mode has no mock form for {url}.",
        hint=f"Add the URL to {root / FORMS_FILE}, or remove `fixtures` from settings.yaml.",
    )


def is_local(url: str) -> bool:
    return url.startswith("file://")

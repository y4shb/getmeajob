"""The workspace: one folder that holds all of a user's personal data.

Layout (all paths relative to `root`):

    profile.yaml  preferences.yaml  companies.yaml  answers.yaml  rules.yaml  settings.yaml
    resume/bank.yaml  resume/base.pdf
    data/jobs.jsonl  data/jd/<key>.txt  data/ranked.jsonl  data/plans/<key>.json
    data/schemas/<key>.json  data/ledger.jsonl  data/events.jsonl  data/queue.jsonl
    data/runs/<ts>.json
    cache/http/  cache/llm/  roles/<role>/  shots/  exports/
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from getmeajob.errors import WorkspaceMissing
from getmeajob.textutil import short_hash

HOME_ENV = "GETMEAJOB_HOME"
MAX_FILENAME = 150
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_LEADING_DOTS = re.compile(r"^\.+")


def key_to_filename(key: str) -> str:
    """A safe file name for a job key: `:` becomes `__`, other unsafe characters `_`.

    Names longer than 150 characters are cut and end with `-<hash of the key>`.
    """
    name = _UNSAFE.sub("_", key.replace(":", "__"))
    name = _LEADING_DOTS.sub(lambda m: "_" * len(m.group(0)), name) or "_"
    if len(name) > MAX_FILENAME:
        suffix = "-" + short_hash(key)
        name = name[: MAX_FILENAME - len(suffix)] + suffix
    return name


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def resolve(cls, home: str | Path | None = None) -> Workspace:
        """Pick the workspace folder: the argument, else GETMEAJOB_HOME, else ./workspace."""
        if home is not None and str(home).strip():
            path = Path(home)
        elif os.environ.get(HOME_ENV, "").strip():
            path = Path(os.environ[HOME_ENV].strip())
        else:
            path = Path.cwd() / "workspace"
        return cls(path.expanduser().resolve())

    def exists(self) -> bool:
        return self.root.is_dir() and self.profile_path.is_file()

    def require(self) -> Workspace:
        """Return self, or raise `WorkspaceMissing` with a hint to run `getmeajob init`."""
        if self.exists():
            return self
        if self.root.is_dir():
            raise WorkspaceMissing(
                f"The folder {self.root} has no profile.yaml, so it is not a getmeajob "
                "workspace yet."
            )
        raise WorkspaceMissing(f"No getmeajob workspace found at {self.root}.")

    def ensure_dirs(self) -> None:
        for path in (
            self.root,
            self.resume_dir,
            self.data_dir,
            self.jd_dir,
            self.plans_dir,
            self.schemas_dir,
            self.runs_dir,
            self.cache_dir,
            self.http_cache_dir,
            self.llm_cache_dir,
            self.roles_dir,
            self.shots_dir,
            self.exports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------- config files

    @property
    def profile_path(self) -> Path:
        return self.root / "profile.yaml"

    @property
    def preferences_path(self) -> Path:
        return self.root / "preferences.yaml"

    @property
    def companies_path(self) -> Path:
        return self.root / "companies.yaml"

    @property
    def answers_path(self) -> Path:
        return self.root / "answers.yaml"

    @property
    def user_rules_path(self) -> Path:
        return self.root / "rules.yaml"

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.yaml"

    @property
    def resume_dir(self) -> Path:
        return self.root / "resume"

    @property
    def resume_bank_path(self) -> Path:
        return self.resume_dir / "bank.yaml"

    # ------------------------------------------------------------------ data

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def jobs_path(self) -> Path:
        return self.data_dir / "jobs.jsonl"

    @property
    def jd_dir(self) -> Path:
        return self.data_dir / "jd"

    @property
    def ranked_path(self) -> Path:
        return self.data_dir / "ranked.jsonl"

    @property
    def plans_dir(self) -> Path:
        return self.data_dir / "plans"

    @property
    def schemas_dir(self) -> Path:
        return self.data_dir / "schemas"

    @property
    def ledger_path(self) -> Path:
        return self.data_dir / "ledger.jsonl"

    @property
    def events_path(self) -> Path:
        return self.data_dir / "events.jsonl"

    @property
    def queue_path(self) -> Path:
        return self.data_dir / "queue.jsonl"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    # ------------------------------------------------------- caches, outputs

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def http_cache_dir(self) -> Path:
        return self.cache_dir / "http"

    @property
    def llm_cache_dir(self) -> Path:
        return self.cache_dir / "llm"

    @property
    def roles_dir(self) -> Path:
        return self.root / "roles"

    @property
    def shots_dir(self) -> Path:
        return self.root / "shots"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    # ------------------------------------------------------- per-job files

    def jd_path(self, key: str) -> Path:
        return self.jd_dir / f"{key_to_filename(key)}.txt"

    def plan_path(self, key: str) -> Path:
        return self.plans_dir / f"{key_to_filename(key)}.json"

    def schema_path(self, key: str) -> Path:
        return self.schemas_dir / f"{key_to_filename(key)}.json"

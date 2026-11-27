"""`getmeajob init [--demo] [--force]`: create a workspace.

Without --demo the workspace gets the commented templates from `config/`.
With --demo it gets the synthetic candidate from `examples/demo/`, a settings file
that replays recorded replies from `examples/fixtures/` (no network), and a
one-page synthetic resume PDF.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from getmeajob.errors import ConfigError
from getmeajob.files import atomic_write_bytes, atomic_write_text
from getmeajob.workspace import Workspace

if TYPE_CHECKING:
    from getmeajob.cli import Context

_PACKAGE_DIR = Path(__file__).resolve().parent

# Where each `config/<name>.example.yaml` template goes in the workspace.
TEMPLATE_TARGETS = {
    "profile": "profile.yaml",
    "preferences": "preferences.yaml",
    "answers": "answers.yaml",
    "companies": "companies.yaml",
    "rules": "rules.yaml",
    "bank": "resume/bank.yaml",
}

DEMO_PDF_LINES = [
    "Alex Example - synthetic resume for the getmeajob demo",
    "",
    "Software Engineer, Initech Example Ltd, 2021 to present",
    "Software Engineering Intern, Globex Example Inc, 2020",
    "Bachelor of Science, Computer Science, Example State University, 2021",
    "",
    "alex@example.com   +1 555 0100   Springfield, Ontario, Canada",
    "This person does not exist. Every detail in this file is made up.",
]

_SETTINGS_HEADER = """\
# getmeajob settings. Every line is optional; delete one to use the default.
# offline: true means getmeajob never uses the network.
# fixtures: a folder of recorded replies to use instead of the network.
# min_interval: seconds between two requests to the same site.
# timeout: seconds to wait for a reply. retries: extra tries after a timeout or busy site.
# max_workers: how many requests may run at the same time.
"""

_WORKSPACE_GITIGNORE = """\
# This folder holds your personal data. Keep it out of every git repository.
*
"""


def _repo_root() -> Path | None:
    """The repository checkout when running from `src/` (not from an installed wheel)."""
    if _PACKAGE_DIR.parent.name == "src":
        return _PACKAGE_DIR.parent.parent
    return None


def _find_dir(repo_name: str, packaged_name: str) -> Path:
    root = _repo_root()
    if root is not None and (root / repo_name).is_dir():
        return root / repo_name
    packaged = _PACKAGE_DIR / packaged_name
    if packaged.is_dir():
        return packaged
    raise ConfigError(
        f"Could not find the getmeajob '{repo_name}' files.",
        hint="Reinstall getmeajob, or run it from a full copy of the repository.",
    )


def examples_dir() -> Path:
    """`examples/` of the checkout, else the copy packaged as `getmeajob/_examples`."""
    return _find_dir("examples", "_examples")


def agents_dir() -> Path:
    """`agents/` of the checkout, else the copy packaged as `getmeajob/_agents`."""
    return _find_dir("agents", "_agents")


def config_dir() -> Path:
    """`config/` of the checkout, else the copy packaged as `getmeajob/_config`."""
    return _find_dir("config", "_config")


# ------------------------------------------------------------------------- PDF


def _pdf_text(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_simple_pdf(path: Path, lines: list[str]) -> None:
    """Write a one-page Letter PDF with the given lines in Helvetica (no dependencies)."""
    ops = ["BT", "/F1 11 Tf", "15 TL", "72 720 Td"]
    for index, line in enumerate(lines):
        ops.append(("" if index == 0 else "T* ") + f"({_pdf_text(line)}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    atomic_write_bytes(path, bytes(out))


# ------------------------------------------------------------------------ init


def _settings_text(fixtures: Path | None) -> str:
    data: dict[str, object] = {}
    if fixtures is not None:
        data["fixtures"] = str(fixtures)
    data.update(offline=fixtures is not None, min_interval=1.0, timeout=25.0, retries=3)
    data["max_workers"] = 4
    return _SETTINGS_HEADER + yaml.safe_dump(data, sort_keys=False)


def _plan_template_copies(source: Path) -> list[tuple[Path, str]]:
    copies: list[tuple[Path, str]] = []
    for template in sorted(source.glob("*.example.yaml")):
        name = template.name.removesuffix(".example.yaml")
        copies.append((template, TEMPLATE_TARGETS.get(name, f"{name}.yaml")))
    return copies


def _plan_demo_copies(source: Path) -> list[tuple[Path, str]]:
    copies: list[tuple[Path, str]] = []
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name not in (".gitkeep", ".DS_Store"):
            copies.append((path, path.relative_to(source).as_posix()))
    return copies


def init_workspace(root: Path, *, demo: bool, force: bool) -> list[str]:
    """Create or refresh a workspace. Returns the files written, relative to `root`."""
    if demo:
        examples = examples_dir()
        copies = _plan_demo_copies(examples / "demo")
        fixtures: Path | None = (examples / "fixtures").resolve()
    else:
        copies = _plan_template_copies(config_dir())
        fixtures = None
    targets = [rel for _, rel in copies] + ["settings.yaml"]
    if demo:
        targets.append("resume/base.pdf")
    existing = [rel for rel in targets if (root / rel).exists()]
    if existing and not force:
        shown = ", ".join(existing[:4]) + (" and more" if len(existing) > 4 else "")
        raise ConfigError(
            f"{root} already has workspace files ({shown}).",
            hint="Add --force to replace them, or use --home PATH to pick another folder.",
        )

    Workspace(root).ensure_dirs()
    for source, rel in copies:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    atomic_write_text(root / "settings.yaml", _settings_text(fixtures))
    if demo:
        write_simple_pdf(root / "resume" / "base.pdf", DEMO_PDF_LINES)
    if not (root / ".gitignore").exists():
        atomic_write_text(root / ".gitignore", _WORKSPACE_GITIGNORE)
        targets.append(".gitignore")
    return targets


def _cmd_init(args: argparse.Namespace, ctx: Context) -> int:
    root = ctx.ws.root
    written = init_workspace(root, demo=bool(args.demo), force=bool(args.force))
    if ctx.out.json_mode:
        ctx.out.emit({"workspace": str(root), "demo": bool(args.demo), "files": written})
        return 0
    if args.demo:
        ctx.out.done(
            f"Created a demo workspace at {root} (synthetic data, offline replies).",
            next_step="getmeajob source",
        )
    else:
        ctx.out.done(
            f"Created a workspace at {root}. Fill in profile.yaml and preferences.yaml there, "
            "and list target companies in companies.yaml.",
            next_step="getmeajob source",
        )
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "init",
        help="create a workspace (add --demo for sample data)",
        description="Create a workspace folder with your config files.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="fill it with a synthetic candidate and recorded replies (no network)",
    )
    parser.add_argument("--force", action="store_true", help="replace files that already exist")
    parser.set_defaults(func=_cmd_init)

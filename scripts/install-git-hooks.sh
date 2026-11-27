#!/usr/bin/env bash
# Installs a git pre-commit hook that runs the privacy scanner on staged files.
# If GETMEAJOB_DENYLIST points to your private list of terms, the hook checks those too.
set -euo pipefail

# Always this repository's own hooks folder, never a shared one from core.hooksPath.
hook_dir="$(git rev-parse --git-common-dir)/hooks"
mkdir -p "$hook_dir"
hook="$hook_dir/pre-commit"
marker="Installed by scripts/install-git-hooks.sh"

if [ -f "$hook" ] && ! grep -q "$marker" "$hook"; then
  mv "$hook" "$hook.backup"
  echo "Moved your existing pre-commit hook to $hook.backup"
fi

cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
# Installed by scripts/install-git-hooks.sh. Blocks commits that contain personal data or secrets.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
if [ -x "$root/.venv/bin/python" ]; then
  python_bin="$root/.venv/bin/python"
else
  python_bin="$(command -v python3 || command -v python)"
fi
args=(--staged)
if [ -n "${GETMEAJOB_DENYLIST:-}" ]; then
  args+=(--denylist "$GETMEAJOB_DENYLIST")
fi
exec "$python_bin" "$root/scripts/scan_sensitive.py" "${args[@]}"
HOOK

chmod +x "$hook"
echo "Installed the pre-commit hook at $hook"
if git config --get core.hooksPath >/dev/null; then
  echo "Note: core.hooksPath is set, so git runs hooks from that folder instead of this one." >&2
  echo "Use the pre-commit tool with .pre-commit-config.yaml, or unset core.hooksPath." >&2
fi

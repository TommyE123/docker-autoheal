#!/usr/bin/env python3
"""PostToolUse hook for Edit/Write: report Ruff findings in an edited Python file.

Runs `ruff check` and `ruff format --check` with the repository's config
(.linter-rules/.ruff.toml), which a plain `ruff` run in the root would not find. It never changes
the file. Findings go to stderr with exit code 2, which shows them to Claude; the edit itself has
already happened. Does nothing when Ruff isn't installed or the file is outside the repository.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT = 4000


def lint(file_path: Path, root: Path) -> str | None:
    """Return a report of Ruff findings for file_path, or None if there are none to report."""
    ruff = shutil.which("ruff")
    config = root / ".linter-rules" / ".ruff.toml"
    if ruff is None or file_path.suffix != ".py" or not config.is_file():
        return None
    if not file_path.is_file() or not file_path.resolve().is_relative_to(root.resolve()):
        return None
    reports = []
    for args in (["check", "--no-fix"], ["format", "--check", "--diff"]):
        result = subprocess.run(  # noqa: S603
            [ruff, *args, "--config", str(config), str(file_path)],
            # Path-based per-file-ignores resolve against the working directory, and a hook runs
            # in the session's current directory, which may be a subdirectory.
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            reports.append(f"$ ruff {' '.join(args)}\n{(result.stdout + result.stderr).strip()}")
    if not reports:
        return None
    report = "\n\n".join(reports)
    if len(report) > MAX_OUTPUT:
        report = report[:MAX_OUTPUT] + "\n... (truncated)"
    return report


def checkout_root(file_path: Path, fallback: Path) -> Path:
    """Return the git checkout that contains file_path, or fallback outside any checkout.

    CLAUDE_PROJECT_DIR stays on the original checkout when Claude works in another worktree, so
    the edited file's own checkout decides which config and working directory apply.
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(file_path.parent), "rev-parse", "--show-toplevel"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return fallback
    except subprocess.SubprocessError:
        return fallback
    toplevel = result.stdout.strip()
    return Path(toplevel) if result.returncode == 0 and toplevel else fallback


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        file_path = payload.get("tool_input", {}).get("file_path")
        if not file_path:
            return 0
        fallback = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
        report = lint(Path(file_path), checkout_root(Path(file_path), fallback))
    except Exception:
        # A broken lint hook must never get in the way of editing.
        return 0
    if report is None:
        return 0
    print(
        "check_python_lint hook (ruff, --config .linter-rules/.ruff.toml) found issues in"
        f" {file_path}:\n{report}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""PostToolUse hook for Edit/Write: report markdownlint findings in an edited Markdown file.

Runs `markdownlint-cli2` with the repository's config (.linter-rules/.markdownlint.jsonc), from the
root of the checkout that contains the file. It uses an installed markdownlint-cli2 and otherwise
`npx`. It never changes the file. Findings go to stderr with exit code 2, which shows them to
Claude; the edit itself has already happened. Does nothing when the linter can't run or the file is
outside the repository. It does not run markdown-table-formatter, which only MegaLinter checks.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from check_python_lint import MAX_OUTPUT, checkout_root

# Used only when markdownlint-cli2 isn't installed. Unpinned, so npx runs the latest release.
NPX_PACKAGE = "markdownlint-cli2"


def lint(file_path: Path, root: Path) -> str | None:
    """Return a report of markdownlint findings for file_path, or None if there are none."""
    config = root / ".linter-rules" / ".markdownlint.jsonc"
    if file_path.suffix != ".md" or not config.is_file() or not file_path.is_file():
        return None
    if not file_path.resolve().is_relative_to(root.resolve()):
        return None
    installed = shutil.which("markdownlint-cli2")
    npx = shutil.which("npx")
    if installed is not None:
        command = [installed]
    elif npx is not None:
        command = [npx, "--yes", NPX_PACKAGE]
    else:
        return None
    result = subprocess.run(  # noqa: S603
        # The ":" prefix makes markdownlint-cli2 treat the path literally, not as a glob.
        [*command, "--config", str(config), f":{file_path.resolve()}"],
        cwd=root,
        # Without this npm retries for about a minute when the registry is unreachable.
        env={**os.environ, "npm_config_fetch_retries": "0"},
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    # Exit 1 with markdownlint-cli2's banner means findings. Anything else is a linter that
    # couldn't run: npx also exits 1 when it can't fetch the package.
    if result.returncode != 1 or "markdownlint-cli2 v" not in result.stdout:
        return None
    report = result.stderr.strip() or result.stdout.strip()
    if len(report) > MAX_OUTPUT:
        report = report[:MAX_OUTPUT] + "\n... (truncated)"
    return report


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
    if not report:
        return 0
    print(
        "check_markdown_lint hook (markdownlint-cli2, --config .linter-rules/.markdownlint.jsonc)"
        f" found issues in {file_path}:\n{report}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())

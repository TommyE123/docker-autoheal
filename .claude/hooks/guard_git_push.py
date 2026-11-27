#!/usr/bin/env python3
"""PreToolUse hook for Bash: guard `git push`.

- Blocks force pushes (-f, --force, --force-with-lease, --mirror, a `+` refspec) and pushes that
  would update or delete `main`. Exit code 2 blocks the command and returns stderr to Claude.
- Asks the user before pushing a branch whose name breaks CLAUDE.md's branch rule, or deleting a
  remote branch, so something the user has explicitly approved can still go ahead.
- Leaves every other command to the normal permission flow.

Best effort: the command is parsed with shlex, looking inside `sh -c`/`bash -c` strings and
`eval`, but variables, aliases and scripts are not seen through. The deny rules in
.claude/settings.json and branch protection on main stay in place.

Claude Code runs this with whatever `python3` is installed, so it must stay valid Python 3.10.
"""

import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

BRANCH_RULE = re.compile(
    r"^(feat|fix|chore|refactor|test|ci|docs|perf|build|style)/"
    r"([0-9]+-)?[a-z0-9]+(-[a-z0-9]+){1,4}$"
)
PROTECTED_BRANCHES = frozenset({"main"})
SEPARATORS = frozenset({"&&", "||", ";", ";;", "|", "|&", "&", "(", ")"})
GIT_OPTIONS_WITH_VALUE = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
)
PUSH_OPTIONS_WITH_VALUE = frozenset({"--repo", "--push-option", "--receive-pack", "--exec"})
FORCE_OPTIONS = frozenset({"--force", "--force-with-lease", "--mirror"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
MAX_NESTING = 3


def _strip_heredocs(command: str) -> str:
    """Drop heredoc bodies, which are data rather than commands."""
    kept: list[str] = []
    pending: list[tuple[bool, str]] = []
    for line in command.split("\n"):
        if pending:
            strip_tabs, word = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == word:
                pending.pop(0)
            continue
        kept.append(line)
        pending = [(m.group(1) == "-", m.group(3)) for m in HEREDOC.finditer(line)]
    # An unterminated "heredoc" was probably text inside quotes; keep everything rather than
    # risk hiding a command.
    return command if pending else "\n".join(kept)


def _tokens(command: str) -> list[str]:
    # Newlines and backticks also separate commands; inside quotes the substitution is harmless.
    text = _strip_heredocs(command).replace("\n", " ; ").replace("`", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    # shlex would treat `#` as a comment to the end of the whole text; _segments ends it at the
    # next separator instead, which includes the end of its line.
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return text.split()


def _segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    skip_next = in_comment = False
    for token in tokens:
        if token in SEPARATORS:
            segments.append([])
            skip_next = in_comment = False
        elif skip_next:
            skip_next = False
        elif in_comment or token.startswith("#"):
            in_comment = True
        elif token and set(token) <= set("<>&|;()") and ("<" in token or ">" in token):
            # Redirection: drop the operator, its target, and a file-descriptor number before it.
            if segments[-1] and segments[-1][-1].isdigit():
                segments[-1].pop()
            skip_next = True
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _git(directory: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(directory), *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    # Two clauses rather than a tuple: Ruff's py315 target rewrites `except (A, B):` into
    # `except A, B:`, which only Python 3.14+ can parse.
    except OSError:
        return None
    except subprocess.SubprocessError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _push_args(segment: list[str], cwd: Path) -> tuple[list[str], Path] | None:
    """Return the arguments after `push` and the repository directory, or None if not a push."""
    try:
        start = next(i for i, token in enumerate(segment) if Path(token).name == "git")
    except StopIteration:
        return None
    directory = cwd
    i = start + 1
    while i < len(segment) and segment[i].startswith("-"):
        option = segment[i]
        if option in GIT_OPTIONS_WITH_VALUE and i + 1 < len(segment):
            if option == "-C":
                directory = directory / segment[i + 1]
            i += 1
        i += 1
    if i >= len(segment) or segment[i] != "push":
        return None
    return segment[i + 1 :], directory


def _is_tag(directory: Path, name: str) -> bool:
    if name.startswith("refs/tags/"):
        return True
    is_branch = _git(directory, "show-ref", "--verify", f"refs/heads/{name}") is not None
    return (
        not is_branch and _git(directory, "show-ref", "--verify", f"refs/tags/{name}") is not None
    )


def _default_target(directory: Path) -> str | None:
    """Where a bare `git push` sends the current branch: its push destination, else its name."""
    destination = _git(directory, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}")
    if destination and "/" in destination:
        return destination.split("/", 1)[1]
    return _git(directory, "symbolic-ref", "--short", "-q", "HEAD")


FORCE_REASON = "force-pushes; CLAUDE.md says never to force-push"


@dataclass
class PushOptions:
    """What `check_push` needs from the arguments of one `git push`."""

    positional: list[str] = field(default_factory=list)
    force: list[str] = field(default_factory=list)
    delete: bool = False
    all_branches: bool = False
    tags: bool = False


def _parse_long_option(arg: str, options: PushOptions) -> bool:
    """Record a `--option`; return True when its value is the next argument."""
    name = arg.split("=", 1)[0]
    if name in FORCE_OPTIONS:
        options.force.append(arg)
    elif name == "--delete":
        options.delete = True
    elif name in {"--all", "--branches"}:
        options.all_branches = True
    elif name in {"--tags", "--follow-tags"}:
        options.tags = True
    return name in PUSH_OPTIONS_WITH_VALUE and "=" not in arg


def _parse_short_options(arg: str, options: PushOptions) -> bool:
    """Record a `-xyz` cluster; return True when its value is the next argument."""
    # `-o <option>` takes a value, attached or as the next argument.
    flags, has_value, attached = arg[1:].partition("o")
    if "f" in flags:
        options.force.append(arg)
    options.delete = options.delete or "d" in flags
    return bool(has_value) and not attached


def parse_push(args: list[str]) -> PushOptions:
    options = PushOptions()
    options_ended = skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
        elif options_ended or arg == "-" or not arg.startswith("-"):
            options.positional.append(arg)
        elif arg == "--":
            options_ended = True
        elif arg.startswith("--"):
            skip_value = _parse_long_option(arg, options)
        else:
            skip_value = _parse_short_options(arg, options)
    return options


def _targets(options: PushOptions, directory: Path) -> list[tuple[str, bool]]:
    """Return (destination branch, is a deletion) for each ref the push would update."""
    refspecs = options.positional[1:]
    if not refspecs:
        current = None if options.tags else _default_target(directory)
        return [(current, options.delete)] if current else []
    targets = []
    for refspec in refspecs:
        source, _, destination = refspec.removeprefix("+").partition(":")
        destination = destination or source
        if destination == "HEAD":
            destination = _git(directory, "symbolic-ref", "--short", "-q", "HEAD") or destination
        targets.append((destination.removeprefix("refs/heads/"), options.delete or not source))
    return targets


def check_push(args: list[str], directory: Path) -> tuple[list[str], list[str]]:
    """Return (reasons to block, reasons to ask the user) for one `git push`."""
    options = parse_push(args)
    blocks = [f"`{arg}` {FORCE_REASON}" for arg in options.force]
    blocks += [
        f"refspec `{refspec}` {FORCE_REASON}"
        for refspec in options.positional[1:]
        if refspec.startswith("+")
    ]
    asks: list[str] = []
    if options.all_branches and not options.positional[1:]:
        asks.append("`--all`/`--branches` pushes every local branch")
        return blocks, asks
    for name, deleting in _targets(options, directory):
        if name in PROTECTED_BRANCHES:
            action = "delete" if deleting else "push to"
            blocks.append(f"don't {action} `{name}`; push a feature branch and open a PR")
        elif deleting:
            asks.append(f"this deletes remote branch `{name}`; CLAUDE.md needs the user's approval")
        elif not deleting and not _is_tag(directory, name) and not BRANCH_RULE.match(name):
            asks.append(
                f"branch `{name}` doesn't match CLAUDE.md's `<type>/<issue>-<slug>` rule"
                " (for example `fix/353-restart-handling`); push it only if the user approved"
                " this name"
            )
    return blocks, asks


def _nested_command(segment: list[str]) -> str | None:
    """Return the command string run by `sh -c '...'` or `eval ...`, if the segment is one."""
    for i, token in enumerate(segment):
        name = Path(token).name
        if name == "eval":
            return " ".join(segment[i + 1 :])
        if name in SHELLS:
            for j in range(i + 1, len(segment) - 1):
                option = segment[j]
                if not option.startswith("-"):
                    break
                if not option.startswith("--") and "c" in option:
                    return segment[j + 1]
    return None


def evaluate(command: str, cwd: Path, depth: int = 0) -> tuple[list[str], list[str]]:
    blocks: list[str] = []
    asks: list[str] = []
    if "push" not in command:
        return blocks, asks
    if depth > MAX_NESTING:
        return ["the command nests shells too deeply to check"], asks
    for segment in _segments(_tokens(command)):
        nested = _nested_command(segment)
        if nested is not None:
            nested_blocks, nested_asks = evaluate(nested, cwd, depth + 1)
            blocks += nested_blocks
            asks += nested_asks
        parsed = _push_args(segment, cwd)
        if parsed is not None:
            segment_blocks, segment_asks = check_push(*parsed)
            blocks += segment_blocks
            asks += segment_asks
    return blocks, asks


def main() -> int:
    command = ""
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command") or ""
        blocks, asks = evaluate(command, Path(payload.get("cwd") or "."))
    except Exception as error:
        if "push" not in command:
            return 0
        # Fail closed for anything that might be a push.
        blocks, asks = [f"the push guard could not check this command ({error})"], []
    if blocks:
        print("Blocked by guard_git_push hook: " + "; ".join(blocks), file=sys.stderr)
        return 2
    if asks:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "guard_git_push hook: " + "; ".join(asks),
            }
        }
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())

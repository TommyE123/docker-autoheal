"""Command-line entry point used by the release workflows.

Every subcommand reads its inputs from files (so nothing untrusted is ever
interpolated into a shell command), writes ``key=value`` pairs to
``$GITHUB_OUTPUT`` and exits non-zero with a GitHub Actions error annotation
when the release state is unsafe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import versioning
from .versioning import MergedPullRequest, ReleaseError, ReleasePlan


def _load(path: str) -> Any:
    """Load a JSON document, or a plain newline-separated list, from ``path``.

    ``gh api --paginate`` outputs one JSON document per page with no outer
    wrapper, so a multi-page response is multiple JSON arrays concatenated.
    When the file starts with ``[`` or ``{`` all top-level documents are
    decoded and their contents merged into a single flat list, so callers
    see a single list regardless of how many pages the API returned.
    """
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] in "[{":
        decoder = json.JSONDecoder()
        items: list = []
        offset = 0
        while offset < len(text):
            while offset < len(text) and text[offset].isspace():
                offset += 1
            if offset >= len(text):
                break
            value, end = decoder.raw_decode(text, offset)
            if isinstance(value, list):
                items.extend(value)
            else:
                items.append(value)
            offset = end
        return items
    return [line.strip() for line in text.splitlines() if line.strip()]


def _names(values: Any) -> list[str]:
    """Accept either ``["a"]`` or GitHub's ``[{"name": "a"}]`` label shape."""
    names = []
    for value in values:
        if isinstance(value, dict):
            name = value.get("name")
            if name:
                names.append(str(name))
        elif value is not None:
            names.append(str(value))
    return names


def load_labels(path: str) -> list[str]:
    return _names(_load(path))


def load_tags(path: str) -> list[str]:
    return _names(_load(path))


def load_pull_requests(path: str) -> list[MergedPullRequest]:
    """Load merged pull requests, de-duplicated by number."""
    requests: dict[int, MergedPullRequest] = {}
    for entry in _load(path):
        if not isinstance(entry, dict):
            raise ReleaseError(f"expected pull request objects in {path}")
        number = entry.get("number")
        if number is None:
            raise ReleaseError(f"pull request without a number in {path}")
        requests[int(number)] = MergedPullRequest(
            number=int(number), labels=tuple(_names(entry.get("labels") or []))
        )
    return [requests[number] for number in sorted(requests)]


def _emit(plan: ReleasePlan) -> None:
    outputs = {
        "release": "true" if plan.release else "false",
        "release_type": plan.release_type,
        "create_tag": "true" if plan.create_tag else "false",
        "current_version": plan.current.tag if plan.current else "",
        "version": plan.version.tag if plan.version else "",
        "version_number": plan.version.number if plan.version else "",
        "reason": plan.reason,
    }

    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as handle:
            for key, value in outputs.items():
                handle.write(f"{key}={value}\n")

    for key, value in outputs.items():
        print(f"{key}={value}")

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(f"{plan.reason}\n\n")


def _validate_pr(args: argparse.Namespace) -> ReleasePlan:
    plan = versioning.plan_from_labels(
        load_labels(args.labels_file),
        load_tags(args.tags_file),
        allow_first_release=args.allow_first_release,
    )
    return plan


def _plan_release(args: argparse.Namespace) -> ReleasePlan:
    return versioning.plan_from_labels(
        load_labels(args.labels_file),
        load_tags(args.tags_file),
        resume_tag=args.resume_tag or None,
        already_released_tag=args.already_released_tag or None,
        allow_first_release=args.allow_first_release,
    )


def _plan_maintenance(args: argparse.Namespace) -> ReleasePlan:
    return versioning.plan_maintenance(
        load_pull_requests(args.pull_requests_file),
        load_tags(args.tags_file),
        resume_tag=args.resume_tag or None,
        already_released_tag=args.already_released_tag or None,
        allow_first_release=args.allow_first_release,
    )


def _resolve_labels(args: argparse.Namespace) -> list[str]:
    """Reconstruct PR labels at merge time from the GitHub Issues event log."""
    events = _load(args.events_file)
    if not isinstance(events, list):
        raise ReleaseError(f"expected a JSON array in {args.events_file}")
    return versioning.labels_at_merge_time(events, args.merged_at)


def _verify_release(args: argparse.Namespace) -> ReleasePlan:
    """Re-run the full validation against the current state of the repository.

    This runs immediately before the release tag is created, because another
    release may have been published since the plan was calculated.
    """
    tags = load_tags(args.tags_file)
    candidate = versioning.Version.parse(args.version)

    if not args.create_tag:
        return versioning.plan_resume(candidate.tag, tags)

    current = versioning.latest_release(tags, allow_first_release=args.allow_first_release)
    versioning.validate_candidate(current, candidate, args.release_type, tags)
    return ReleasePlan(
        release=True,
        release_type=args.release_type,
        reason=f"{candidate.tag} is still a valid new {args.release_type} "
        f"release after {current.tag}",
        current=current,
        version=candidate,
        create_tag=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="release", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--tags-file",
            required=True,
            help="file listing every existing Git tag",
        )
        subparser.add_argument(
            "--allow-first-release",
            action="store_true",
            help="treat a repository with no release tag as its first release",
        )

    validate_pr = subparsers.add_parser(
        "validate-pr", help="validate a pull request's release classification"
    )
    validate_pr.add_argument("--labels-file", required=True)
    add_common(validate_pr)
    validate_pr.set_defaults(handler=_validate_pr)

    plan_release = subparsers.add_parser(
        "plan-release", help="plan the release for a merged pull request"
    )
    plan_release.add_argument("--labels-file", required=True)
    plan_release.add_argument("--resume-tag", default="")
    plan_release.add_argument(
        "--already-released-tag",
        default="",
        help="the tag already published on this commit, if any - short-circuits "
        "to no-release so re-running the workflow never publishes a second "
        "release for the same commit",
    )
    add_common(plan_release)
    plan_release.set_defaults(handler=_plan_release)

    plan_maintenance = subparsers.add_parser(
        "plan-maintenance", help="plan the Friday maintenance release"
    )
    plan_maintenance.add_argument("--pull-requests-file", required=True)
    plan_maintenance.add_argument("--resume-tag", default="")
    plan_maintenance.add_argument("--already-released-tag", default="")
    add_common(plan_maintenance)
    plan_maintenance.set_defaults(handler=_plan_maintenance)

    verify_release = subparsers.add_parser(
        "verify-release", help="re-validate a planned release before publishing"
    )
    verify_release.add_argument("--version", required=True)
    verify_release.add_argument("--release-type", default="patch")
    verify_release.add_argument(
        "--create-tag",
        choices=("true", "false"),
        default="true",
        help="false when resuming a release whose tag already exists",
    )
    add_common(verify_release)
    verify_release.set_defaults(handler=_verify_release)

    resolve_labels = subparsers.add_parser(
        "resolve-labels",
        help="reconstruct PR labels at merge time from the issue event log",
    )
    resolve_labels.add_argument(
        "--events-file",
        required=True,
        help="path to the GitHub Issues Events API JSON for the pull request",
    )
    resolve_labels.add_argument(
        "--merged-at",
        required=True,
        help="ISO 8601 timestamp of when the pull request was merged",
    )
    resolve_labels.set_defaults(handler=_resolve_labels)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "create_tag"):
        args.create_tag = args.create_tag == "true"

    try:
        result = args.handler(args)
    except (ReleaseError, json.JSONDecodeError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    if isinstance(result, ReleasePlan):
        _emit(result)
    else:
        # resolve-labels: output a JSON array of label names to stdout
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

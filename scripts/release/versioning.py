"""Semantic-version calculation and safety checks for Docker Auto-Heal releases.

A pull request's ``release:*`` label is the only input that decides *what kind*
of release happens. Every version number is derived here from the latest
published release tag, so nothing outside this module ever picks a version.

Every function fails closed: an ambiguous or unexpected release state raises
``ReleaseError`` rather than falling back to a guessed version.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

RELEASE_LABEL_PREFIX = "release:"
RELEASE_TYPES = ("none", "patch", "minor", "major")
VERSION_BUMPS = ("patch", "minor", "major")
RELEASE_LABELS = tuple(RELEASE_LABEL_PREFIX + name for name in RELEASE_TYPES)
RELEASE_NONE_LABEL = RELEASE_LABEL_PREFIX + "none"

TAG_PATTERN = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class ReleaseError(Exception):
    """Raised when the release state is unsafe, ambiguous or unclassified."""


@dataclass(frozen=True, order=True)
class Version:
    """A released version, always rendered as the ``vMAJOR.MINOR.PATCH`` tag."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, tag: str) -> Version:
        match = TAG_PATTERN.match(tag.strip())
        if match is None:
            raise ReleaseError(f"{tag!r} is not a valid release tag; expected vMAJOR.MINOR.PATCH")
        major, minor, patch = (int(part) for part in match.groups())
        return cls(major, minor, patch)

    @property
    def tag(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"

    @property
    def number(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __str__(self) -> str:
        return self.tag

    def bump(self, release_type: str) -> Version:
        if release_type == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        if release_type == "minor":
            return Version(self.major, self.minor + 1, 0)
        if release_type == "major":
            return Version(self.major + 1, 0, 0)
        raise ReleaseError(f"release type {release_type!r} does not produce a new version")


# The base used when a repository has never published a release tag.
FIRST_RELEASE_BASE = Version(0, 0, 0)


def labels_at_merge_time(
    events: Iterable[dict],
    merged_at: str,
) -> list[str]:
    """Reconstruct the label set on a PR at the moment it was merged.

    Replays the ``labeled`` and ``unlabeled`` entries from the GitHub Issues
    Events API, stopping when the ``merged`` event is reached.  The ``merged``
    event is the authoritative replay boundary: any label change recorded after
    it—even one that shares the same ``created_at`` second as the merge—is
    excluded.  GitHub Issue Event timestamps have second precision, so a
    post-merge label change can carry an identical ``created_at`` as
    ``merged_at``; only the ``merged`` event's position in the sorted log
    (by ``created_at``, then ``id``) reliably separates pre- from post-merge.

    Fails closed: raises ``ReleaseError`` when no ``merged`` event is present,
    rather than silently accepting an ambiguous label state.  The event log is
    append-only, so this makes release classification effectively immutable.
    """
    found_merged = False
    labels: set[str] = set()
    for event in sorted(events, key=lambda e: (e.get("created_at") or "", e.get("id") or 0)):
        event_type = event.get("event") or ""
        if event_type == "merged":
            found_merged = True
            break
        label_obj = event.get("label") or {}
        label_name = (label_obj.get("name") or "") if isinstance(label_obj, dict) else ""
        if not label_name:
            continue
        if event_type == "labeled":
            labels.add(label_name)
        elif event_type == "unlabeled":
            labels.discard(label_name)
    if not found_merged:
        raise ReleaseError(
            "cannot reconstruct labels at merge time: no 'merged' event in the issue event log"
        )
    return sorted(labels)


@dataclass(frozen=True)
class MergedPullRequest:
    """A merged pull request considered by the Friday maintenance release."""

    number: int
    labels: Sequence[str] = ()

    @property
    def is_maintenance_change(self) -> bool:
        return classify(self.labels) == "none"


@dataclass(frozen=True)
class ReleasePlan:
    """What the release controller should do for one triggering event."""

    release: bool
    release_type: str
    reason: str
    current: Version | None = None
    version: Version | None = None
    create_tag: bool = False


def classify(labels: Iterable[str]) -> str:
    """Return the release type named by exactly one ``release:*`` label."""
    found = sorted(
        {label.strip() for label in labels if label.strip().startswith(RELEASE_LABEL_PREFIX)}
    )
    invalid = [label for label in found if label not in RELEASE_LABELS]
    if invalid:
        raise ReleaseError(
            "invalid release classification label(s): "
            + ", ".join(invalid)
            + "; expected one of "
            + ", ".join(RELEASE_LABELS)
        )
    if not found:
        raise ReleaseError(
            "no release classification label; add exactly one of " + ", ".join(RELEASE_LABELS)
        )
    if len(found) > 1:
        raise ReleaseError(
            "more than one release classification label: "
            + ", ".join(found)
            + "; exactly one is required"
        )
    return found[0][len(RELEASE_LABEL_PREFIX) :]


def release_versions(tags: Iterable[str]) -> list[Version]:
    """Every tag that is a valid release tag, in ascending version order."""
    versions = []
    for tag in tags:
        candidate = tag.strip()
        if TAG_PATTERN.match(candidate):
            versions.append(Version.parse(candidate))
    return sorted(versions)


def latest_release(tags: Iterable[str], *, allow_first_release: bool = False) -> Version:
    """The highest existing release tag, or the first-release base."""
    versions = release_versions(tags)
    if versions:
        return versions[-1]
    if allow_first_release:
        return FIRST_RELEASE_BASE
    raise ReleaseError("could not determine the current release: no vMAJOR.MINOR.PATCH tag exists")


def validate_candidate(
    current: Version,
    candidate: Version,
    release_type: str,
    tags: Iterable[str],
) -> None:
    """Raise unless ``candidate`` is a new, valid tag for ``release_type``."""
    existing = {tag.strip() for tag in tags}
    if candidate.tag in existing:
        raise ReleaseError(
            f"release tag {candidate.tag} already exists; refusing to reuse, "
            "move or overwrite an existing release tag"
        )
    expected = current.bump(release_type)
    if candidate != expected:
        raise ReleaseError(
            f"{candidate.tag} is not the {release_type} release after "
            f"{current.tag}; expected {expected.tag}"
        )
    if candidate <= current:
        raise ReleaseError(f"{candidate.tag} is not greater than the current release {current.tag}")


def plan_version(
    release_type: str,
    tags: Iterable[str],
    *,
    allow_first_release: bool = False,
) -> ReleasePlan:
    """Calculate and validate the release produced by ``release_type``."""
    if release_type not in RELEASE_TYPES:
        raise ReleaseError(
            f"invalid release type {release_type!r}; expected one of " + ", ".join(RELEASE_TYPES)
        )
    if release_type == "none":
        return ReleasePlan(
            release=False,
            release_type="none",
            reason="release:none - no immediate release; deferred to the next "
            "Friday maintenance release",
        )

    tags = list(tags)
    current = latest_release(tags, allow_first_release=allow_first_release)
    candidate = current.bump(release_type)
    validate_candidate(current, candidate, release_type, tags)
    return ReleasePlan(
        release=True,
        release_type=release_type,
        reason=f"{release_type} release {candidate.tag} calculated from {current.tag}",
        current=current,
        version=candidate,
        create_tag=True,
    )


def plan_already_released(released_tag: str, tags: Iterable[str]) -> ReleasePlan:
    """Nothing to do: this exact commit already has a published release.

    Re-running the release workflow on a commit that was already fully
    released (tag created, image published, GitHub Release created) must
    never calculate the next version - that would publish an extra release
    for no new change. This takes priority over everything else: whatever
    the merged pull request's label says, or however many release:none
    pull requests have accumulated, there is nothing left to release here.
    """
    tags = list(tags)
    released = Version.parse(released_tag)
    existing = {tag.strip() for tag in tags}
    if released.tag not in existing:
        raise ReleaseError(f"cannot skip as already released: {released.tag} does not exist")
    return ReleasePlan(
        release=False,
        release_type="none",
        reason=f"{released.tag} is already released on this commit; nothing to do",
        current=released,
        create_tag=False,
    )


def plan_resume(resume_tag: str, tags: Iterable[str]) -> ReleasePlan:
    """Continue an earlier release attempt that already created its tag."""
    tags = list(tags)
    resumed = Version.parse(resume_tag)
    existing = {tag.strip() for tag in tags}
    if resumed.tag not in existing:
        raise ReleaseError(f"cannot resume release {resumed.tag}: the tag does not exist")
    newest = latest_release(tags)
    if resumed != newest:
        raise ReleaseError(f"cannot resume release {resumed.tag}: {newest.tag} is a newer release")
    return ReleasePlan(
        release=True,
        release_type="resume",
        reason=f"resuming the incomplete release {resumed.tag} using its existing tag",
        current=resumed,
        version=resumed,
        create_tag=False,
    )


def plan_from_labels(
    labels: Iterable[str],
    tags: Iterable[str],
    *,
    resume_tag: str | None = None,
    already_released_tag: str | None = None,
    allow_first_release: bool = False,
) -> ReleasePlan:
    """Plan the release for a merged pull request's classification labels."""
    if already_released_tag:
        return plan_already_released(already_released_tag, tags)
    release_type = classify(labels)
    if release_type == "none":
        return plan_version("none", tags)
    if resume_tag:
        return plan_resume(resume_tag, tags)
    return plan_version(release_type, tags, allow_first_release=allow_first_release)


def plan_maintenance(
    pull_requests: Iterable[MergedPullRequest],
    tags: Iterable[str],
    *,
    resume_tag: str | None = None,
    already_released_tag: str | None = None,
    allow_first_release: bool = False,
) -> ReleasePlan:
    """Plan the Friday maintenance release for unreleased ``release:none`` work.

    ``pull_requests`` must already be limited to pull requests merged after the
    commit of the latest successful release, so changes swept up by an earlier
    release are never released twice.
    """
    if already_released_tag:
        return plan_already_released(already_released_tag, tags)
    if resume_tag:
        return plan_resume(resume_tag, tags)

    deferred = []
    for request in pull_requests:
        release_type = classify(request.labels)
        if release_type != "none":
            raise ReleaseError(
                f"pull request #{request.number} carries release classification "
                f"{release_type!r}; the Friday maintenance sweep cannot release "
                f"a pending {release_type}; re-run the release for that pull request instead"
            )
        deferred.append(request)

    if not deferred:
        return ReleasePlan(
            release=False,
            release_type="none",
            reason="no unreleased release:none pull requests since the latest release",
        )

    numbers = ", ".join(f"#{request.number}" for request in deferred)
    plan = plan_version("patch", tags, allow_first_release=allow_first_release)
    return ReleasePlan(
        release=True,
        release_type="patch",
        reason=(
            f"maintenance patch release {plan.version} for "
            f"{len(deferred)} unreleased release:none pull request(s): {numbers}"
        ),
        current=plan.current,
        version=plan.version,
        create_tag=True,
    )

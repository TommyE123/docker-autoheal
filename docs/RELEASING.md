# Releasing

Releases are produced by exactly one controller: `.github/workflows/docker-release.yml`.
It owns the Git tag, the Docker images on Docker Hub and GHCR, and the GitHub Release.
Nothing else creates release tags, and no other release/versioning system is installed.

## Release classification

Every pull request into `main` carries **exactly one** release label. The author (human
or AI agent) chooses the release *type* only — the version number is always calculated by
the automation, never by hand.

| Change                                            | Label           |
|---------------------------------------------------|-----------------|
| Documentation only                                | `release:none`  |
| CI-only change                                    | `release:none`  |
| Tests only                                        | `release:none`  |
| Refactor with no behaviour change                 | `release:none`  |
| Normal Renovate dependency update                 | `release:none`  |
| Formatting/linting with no runtime change         | `release:none`  |
| Bug fix                                           | `release:patch` |
| Security fix requiring a new image                | `release:patch` |
| Performance improvement                           | `release:patch` |
| New backwards-compatible feature                  | `release:minor` |
| New configuration option                          | `release:minor` |
| Intentional backwards-compatible behaviour change | `release:minor` |
| Breaking behaviour/configuration change           | `release:major` |

The automation never infers the release type from the code, the commit message or the
pull request title — the label is authoritative. Renovate applies `release:none` to its
own pull requests automatically (`renovate.json`).

## Before merge: the `validate-release` check

`.github/workflows/release-validation.yml` runs on every pull request into `main` and fails
when a pull request's release classification is invalid. It is not yet configured as a
required status check on `main` — see "Required check: manual setup" below for why and what
that means until it is enabled. It fails when:

- there is no release label, more than one, or an invalid one;
- the current release cannot be determined;
- the calculated candidate version is invalid, or is not the requested release type;
- the calculated release tag already exists.

It uses no secrets and needs no registry credentials. Its result is never trusted on its
own: `docker-release.yml` repeats the whole validation from `main` immediately before it
publishes, so a pull request cannot talk the release automation into an unsafe release by
altering the tooling.

### Required check: manual setup

`validate-release` is not yet a required status check in the "Protect Main" ruleset. GitHub
rulesets are repository configuration, not a file this repository can define or change — an
administrator has to add `validate-release` to the ruleset's required status checks through
GitHub's settings (or the API) before a pull request without a valid release label is
actually blocked from merging. Enabling it before this workflow exists on `main` would block
every open pull request against a check that cannot yet run, so it is deliberately turned on
only after this change merges. Until it is enabled, an invalid or missing release
classification will show as a failed check on the PR, but does not by itself prevent a
merge.

## Version calculation

The latest `vMAJOR.MINOR.PATCH` tag is the source of truth. From `v1.8.4`:

| Label           | Next release |
|-----------------|--------------|
| `release:patch` | `v1.8.5`     |
| `release:minor` | `v1.9.0`     |
| `release:major` | `v2.0.0`     |

The calculation never depends on how many pull requests are being released.

## After merge: the release run

`release:patch`, `release:minor` and `release:major` release immediately on merge — they
never wait for Friday. The workflow runs in the `release-publication` concurrency group
with `cancel-in-progress: false`, so releases are processed one at a time, in this order:

1. determine the release type from the labels of all pull requests merged since the latest
   release tag, selecting the highest-priority classification; this reconciliation approach
   ensures no release is lost when GitHub Actions concurrency displaces a pending run;
2. determine the current release;
3. calculate and validate the candidate version;
4. **re-validate everything against the current state of `main`, using trusted tooling** —
   before re-deriving the plan, the job restores `scripts/release/` from a revision the merged
   PR could not have modified (the pre-push tip of `main` for a normal push, or the latest
   release tag for `schedule`/`workflow_dispatch`), then re-runs the whole classification and
   plan calculation with that trusted copy and the raw GitHub API data. The result must match
   the plan job's output exactly; a mismatch aborts the release. This stops a pull request
   from inflating its own release type or version by editing `scripts/release/` itself — the
   privileged job never trusts that code's own validation of itself. The image is still built
   from the merged commit's own code, only the release-safety validator runs from a trusted
   copy;
5. create the Git tag through the Git references API, which refuses to create a reference
   that already exists;
6. verify the tag points at the release commit;
7. build and publish the multi-architecture image to Docker Hub and GHCR as
   `<image>:vMAJOR.MINOR.PATCH` (the immutable version image only);
8. create the GitHub Release;
9. promote `<image>:latest` to the new version image (in a separate retryable job,
   so a failed promotion can be retried without rebuilding the version image or
   creating another GitHub Release).

No image is published before its release tag is safely established, and a tag is never
moved, deleted, recreated or force-pushed: a conflict fails the release instead.

## `release:none` and the Friday maintenance release

`release:none` means *"no immediate release, but include this in the next scheduled
maintenance release unless an earlier release already picked it up"*.

Every Friday at 09:00 UTC the workflow looks for merged `release:none` pull requests
**after the commit of the latest release tag**:

- none found — nothing happens, and no release is created;
- one or more found — exactly one **patch** release is created, however many accumulated.

Because the boundary is the latest release tag, a `release:none` change that was already
swept up by a normal patch/minor/major release is never released a second time.

## Retrying a failed release, and re-running a successful one

Re-run the failed workflow run. A release tag on the release commit that has no published
GitHub Release marks an incomplete attempt: the run resumes that exact version and
completes the remaining steps. The version is never incremented because an earlier attempt
failed, and a duplicate tag is never created.

If the commit's release already fully succeeded (its tag *and* its GitHub Release both
exist), re-running the workflow — a manual "re-run all jobs", or `workflow_dispatch` with
`auto` pointed at that same commit — is a no-op: the plan step recognises the commit is
already released and reports nothing to do, rather than calculating the next version on
top of it.

`workflow_dispatch` offers the same behaviour manually:

| Input         | Effect                                                                    |
|---------------|---------------------------------------------------------------------------|
| `auto`        | Re-run the classification of the latest commit on `main` (the retry path) |
| `maintenance` | Run the Friday maintenance sweep now                                      |

There is deliberately no manual `patch`/`minor`/`major` option. Every release must trace
back to a merged pull request's `release:*` label — a manual dispatch that picked the
release type directly would bypass the required `validate-release` PR check entirely.

If an unpublished tag exists anywhere else in the repository's history — a release that
stalled on a different, earlier commit — every other release path refuses to run until it
is resumed. Otherwise a normal release would silently calculate the next version past it,
or the Friday sweep would use its commit as the boundary and permanently lose the
`release:none` pull requests that were meant to ride the next release.

## Bootstrapping

The release-time re-derivation (see step 4 above) restores `scripts/release/` from
`github.event.before` — the tip of `main` immediately before the push — so the plan can be
re-checked with tooling the pushed commit could not have modified. That has no answer for the
one commit that introduces `scripts/release/` onto `main` for the first time: `before` has no
`scripts/` at all, so there is nothing trusted to restore, and falling back to the pushed
commit's own copy would let that commit's tooling validate itself. The release job fails
closed in that case instead: it errors out before creating any tag or publishing any image.

This means the commit that adds `scripts/release/` never releases itself automatically — that
is intentional, not a bug. Every following push has `scripts/release/` at its own
`before` commit and is validated normally from then on. Nothing further needs to be done: the
next pull request merged into `main` triggers a normal, fully re-derived release.

## Ref safety

Both jobs refuse to run unless `github.ref` is `refs/heads/main`, checked before either one
checks out any code. `push` is already restricted to `main` by its own trigger and
`schedule` always runs the default branch, but `workflow_dispatch` lets a caller pick any
branch or tag to run the workflow against — without this guard, dispatching `maintenance`
against a feature branch would tag and publish that unmerged commit, including moving
`latest` to code that was never reviewed or merged.

## The tooling

`scripts/release/` holds the version calculation and safety rules used by both workflows:

- `versioning.py` — classification, version calculation and the safety checks. Every
  function fails closed: an ambiguous or unexpected release state raises rather than
  guessing a version.
- `cli.py` — the `validate-pr`, `plan-push`, `plan-maintenance` and `verify-release`
  subcommands the workflows call. `plan-push` is the reconciliation planner used on
  every push: it scans all PRs merged since the latest release and selects the
  highest-priority classification.

Both are covered by `app/tests/unit/test_release_versioning.py`, which runs in the normal
unit-test suite.

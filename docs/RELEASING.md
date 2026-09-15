# Releasing

Releases are produced by exactly one controller: `.github/workflows/docker-release.yml`.
It owns the Git tag, the Docker images on Docker Hub and GHCR, and the GitHub Release.
Nothing else creates release tags, and no other release/versioning system is installed.

## Release classification

Every pull request into `main` carries **exactly one** release label. The author (human
or AI agent) chooses the release *type* only — the version number is always calculated by
the automation, never by hand.

| Change | Label |
| --- | --- |
| Documentation only | `release:none` |
| CI-only change | `release:none` |
| Tests only | `release:none` |
| Refactor with no behaviour change | `release:none` |
| Normal Renovate dependency update | `release:none` |
| Formatting/linting with no runtime change | `release:none` |
| Bug fix | `release:patch` |
| Security fix requiring a new image | `release:patch` |
| Performance improvement | `release:patch` |
| New backwards-compatible feature | `release:minor` |
| New configuration option | `release:minor` |
| Intentional backwards-compatible behaviour change | `release:minor` |
| Breaking behaviour/configuration change | `release:major` |

The automation never infers the release type from the code, the commit message or the
pull request title — the label is authoritative. Renovate applies `release:none` to its
own pull requests automatically (`renovate.json`).

## Before merge: the `validate-release` check

`.github/workflows/release-validation.yml` runs on every pull request into `main` and is a
required status check, so a pull request cannot merge without a valid classification. It
fails when:

- there is no release label, more than one, or an invalid one;
- the current release cannot be determined;
- the calculated candidate version is invalid, or is not the requested release type;
- the calculated release tag already exists.

It uses no secrets and needs no registry credentials. Its result is never trusted on its
own: `docker-release.yml` repeats the whole validation from `main` immediately before it
publishes, so a pull request cannot talk the release automation into an unsafe release by
altering the tooling.

## Version calculation

The latest `vMAJOR.MINOR.PATCH` tag is the source of truth. From `v1.8.4`:

| Label | Next release |
| --- | --- |
| `release:patch` | `v1.8.5` |
| `release:minor` | `v1.9.0` |
| `release:major` | `v2.0.0` |

The calculation never depends on how many pull requests are being released.

## After merge: the release run

`release:patch`, `release:minor` and `release:major` release immediately on merge — they
never wait for Friday. The workflow runs in the `release-publication` concurrency group
with `cancel-in-progress: false`, so releases are processed one at a time, in this order:

1. determine the release type from the merged pull request's label;
2. determine the current release;
3. calculate and validate the candidate version;
4. **re-validate everything against the current state of `main`** — another release may
   have been published since the pull request was validated, and a stale validation result
   is never trusted;
5. create the Git tag through the Git references API, which refuses to create a reference
   that already exists;
6. verify the tag points at the release commit;
7. build and publish the multi-architecture image to Docker Hub and GHCR as
   `<image>:vMAJOR.MINOR.PATCH` and `<image>:latest`;
8. create the GitHub Release.

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

| Input | Effect |
| --- | --- |
| `auto` | Re-run the classification of the latest commit on `main` (the retry path) |
| `maintenance` | Run the Friday maintenance sweep now |

There is deliberately no manual `patch`/`minor`/`major` option. Every release must trace
back to a merged pull request's `release:*` label — a manual dispatch that picked the
release type directly would bypass the required `validate-release` PR check entirely.

## The tooling

`scripts/release/` holds the version calculation and safety rules used by both workflows:

- `versioning.py` — classification, version calculation and the safety checks. Every
  function fails closed: an ambiguous or unexpected release state raises rather than
  guessing a version.
- `cli.py` — the `validate-pr`, `plan-release`, `plan-maintenance` and `verify-release`
  subcommands the workflows call.

Both are covered by `app/tests/unit/test_release_versioning.py`, which runs in the normal
unit-test suite.

---
name: sourcery-review

description: Handle Sourcery's secondary automatic PR review process. Use when a Sourcery review exists on a PR, or when checking whether one exists. Sourcery is a secondary reviewer that may provide input before the mandatory CodeRabbit review stage and is not normally a merge gate.
---

# Sourcery Review

## Purpose

Sourcery is a secondary automated reviewer that may provide input before the mandatory CodeRabbit review stage.

CodeRabbit remains the repository's mandatory PR review process.

Sourcery reviews eligible pull requests automatically through its GitHub App. It does not review every PR — a review may simply not appear.

A missing Sourcery review is not, by itself, a reason to block a pull request.

Do not use Sourcery as a replacement for CodeRabbit.

Follow `.claude/rules/review-fix-workflow.md` for REVIEW.md authority, assessing findings, fixing findings, disputed findings, CI handling, and commit and push behaviour. This skill covers only what's specific to Sourcery: detecting a review, its optional/secondary status, and reply/documentation timing.

## Review Model

The expected workflow is:

Sourcery review, if available
→ assess findings
→ fix valid findings
→ targeted validation
→ CI green
→ proceed to CodeRabbit

If no Sourcery review exists, proceed with the normal CodeRabbit process once the PR is otherwise ready.

Sourcery does not normally require a re-review after fixes.

## Before Considering the Review Complete

Sourcery should be assessed before the CodeRabbit review is requested.

1. Check whether Sourcery has reviewed the current PR state.
2. If a review exists, read and assess it.
3. If no review exists, continue with the normal repository process without waiting for one.
4. If actionable findings exist, resolve them before proceeding to CodeRabbit.
5. Ensure relevant validation has passed.
6. Ensure the branch satisfies `.claude/rules/branch-currency.md` before pushing any Sourcery fixes.
7. Check the current CI status.
8. Do not proceed to CodeRabbit until the relevant CI checks are green.
9. Do not manually trigger an initial Sourcery review.

The review author may appear as either:

`sourcery-ai` or `sourcery-ai[bot]`

Match both spellings — which one is returned depends on the API surface used, and matching only one risks concluding that no review exists when one does.

Check both PR reviews and PR comments when determining whether a Sourcery review exists.

If no Sourcery review exists at the time of assessment, do not block the PR waiting for one, and do not trigger one. Continue with the normal CodeRabbit and repository review process.

## Assessing and Fixing Findings

Apply the shared workflow. Treat no actionable findings as a successful review outcome, and take no further Sourcery action unless the owner explicitly requests a re-review. Keep commits focused on the Sourcery findings being addressed, using the repository's normal commit conventions.

Do not reply on Sourcery's comment threads yet — replies happen only after the fix is pushed and CI is green. See CI below.

## Documenting Resolution

Replies are posted only once the fix exists as a pushed commit and CI is green on it. Do not post replies or a documenting comment while a fix is only staged locally or CI is still running on it. Wait until CI is green on the commit that carries the fix (see CI below), then, in one pass:

1. Reply on each Sourcery comment thread the fix addresses, naming the commit.
2. Leave a concise PR comment documenting the resolved findings.

For example:

```text
Addressed the actionable Sourcery findings:

- Fixed "<finding>" in `<file>`.
- Fixed "<finding>" in `<file>`.

Validation completed:
- <checks>
```

Only mention a branch update if the branch was actually updated.

## CI

Follow the shared CI handling in `.claude/rules/review-fix-workflow.md`, with one addition specific to Sourcery: if CI is still running or failing, do not reply or comment yet. Do not poll — report the CI status and stop, then post the replies when invoked again with CI green on the commit carrying the fix. Once CI is green on that commit, post the thread replies and documenting comment from "Documenting Resolution" in a single pass.

Do not proceed to CodeRabbit while relevant CI is failing or still running. Unrelated or pre-existing CI failures are not automatically Sourcery findings.

## Relationship With CodeRabbit

Sourcery findings should be resolved before the initial CodeRabbit review when a Sourcery review is available. If no Sourcery review exists, proceed without blocking.

CodeRabbit remains the mandatory final automated review stage. Do not create automated coordination, dependencies, or feedback loops between Sourcery and CodeRabbit.

## Subsequent Changes

A Sourcery review covers the PR state available when Sourcery reviews it.

Subsequent material changes may result from:

- Sourcery findings.
- CodeRabbit findings.
- MegaLinter or other CI findings.
- Human review.
- Changes requested by the repository owner.

Do not assume subsequent changes will receive another Sourcery review.

Material changes remain subject to the mandatory CodeRabbit process.

If material changes are made after CodeRabbit has reviewed the PR, follow the CodeRabbit follow-up process. Claude requests a targeted CodeRabbit review once CI is green.

Do not request another Sourcery review merely because changes were made.

Purely editorial or mechanical changes require no special Sourcery handling.

## Explicit Sourcery Re-Review Requests

Only request or perform a Sourcery re-review when the repository owner explicitly asks for one.

If an approved workflow exists and the owner requests it, assess the resulting review using this skill and the shared workflow, then document the resolution where appropriate.

A Sourcery re-review does not replace or alter the mandatory CodeRabbit process.

## Completion

The Sourcery stage is complete when:

1. Any available Sourcery review has been assessed.
2. Valid actionable findings have been resolved or disputed findings have been escalated to the owner.
3. Relevant validation has passed.
4. Branch currency has been checked against `.claude/rules/branch-currency.md`, and the branch updated if that was needed.
5. Relevant CI is green before proceeding to CodeRabbit.
6. If no Sourcery review exists, the PR has not been blocked waiting for one.
7. The PR is ready for the mandatory CodeRabbit review.

Do not merge the PR. The repository owner is the final gatekeeper for merging.

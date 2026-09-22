---
name: sourcery-review

description: Handle Sourcery's secondary automatic PR review process. Use when a Sourcery review exists on a PR, or when checking whether one exists. Sourcery is a secondary reviewer that may provide input before the mandatory CodeRabbit review stage and is not normally a merge gate.
---

# Sourcery Review

## Purpose

Sourcery is a secondary automated reviewer that may provide input before the mandatory CodeRabbit review stage.

CodeRabbit remains the repository's mandatory PR review process.

Sourcery reviews eligible pull requests automatically through its GitHub App when review capacity is available.

A missing Sourcery review is not, by itself, a reason to block a pull request.

Do not use Sourcery as a replacement for CodeRabbit.

## Review Model

The expected workflow is:

Sourcery review, if available
→ assess findings
→ fix valid findings
→ targeted validation
→ CI green
→ proceed to CodeRabbit

If no Sourcery review exists, proceed with the normal CodeRabbit process once the PR is otherwise ready.

Do not create automated coordination, dependencies, or feedback loops between Sourcery and CodeRabbit.

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

The verified review author is:

`sourcery-ai`

Do not search for:

`sourcery-ai[bot]`

Check both PR reviews and PR comments when determining whether a Sourcery review exists.

If no Sourcery review exists at the time of assessment, do not block the PR waiting for one.

## REVIEW.md

Use `REVIEW.md` as the repository-specific review standard.

`REVIEW.md` takes precedence over generic Sourcery recommendations where they conflict.

Findings must still be assessed against the actual code and PR scope.

## Assessing Findings

When Sourcery has reviewed the PR:

1. Read the complete review.
2. Assess each finding against the actual code and PR scope.
3. Apply `REVIEW.md`.
4. Treat no actionable findings as a successful review outcome.
5. Take no further Sourcery action unless the owner explicitly requests a re-review.
6. Only valid, actionable, PR-related findings require action.

Ignore findings that are:

- Incorrect.
- Pre-existing and not materially affected by the PR.
- Speculative without a credible failure path.
- Purely stylistic.
- Already covered by existing tooling without a distinct issue.
- Outside the PR scope.

Do not manufacture findings or turn the Sourcery review into a general repository audit.

## Fixing Findings

For each valid finding:

1. Confirm the reported behaviour.
2. Determine whether the PR introduces or materially worsens the issue.
3. Make the smallest appropriate fix.
4. Keep the fix within the PR scope.
5. Follow `.claude/rules/testing.md`.
6. Ensure branch currency before pushing.
7. Commit and push the focused fix.

Do not change code solely because Sourcery suggested it.

## Disputed Findings

If Claude disagrees with a Sourcery finding:

- Do not change the code solely to satisfy Sourcery.
- Do not silently dismiss the finding.
- Present the owner with:
  - the finding;
  - Claude's assessment;
  - the relevant code or behaviour;
  - the specific reason for disagreement;
  - supporting evidence or validation.

The repository owner decides whether a disputed finding should be fixed or otherwise addressed.

## Validation

After making fixes:

- Run the smallest relevant validation required by `.claude/rules/testing.md`.
- Do not claim checks were run unless they were actually run.
- Do not broaden validation unnecessarily.

## Branch Currency

Before pushing a Sourcery fix:

1. Follow `.claude/rules/branch-currency.md`.
2. Update the branch if required.
3. Rerun affected validation after the update.

The branch must also be current before the initial CodeRabbit review.

## Commit and Push

Use the repository's normal commit conventions.

Keep commits focused on the Sourcery findings being addressed.

Push the changes to the PR branch.

## Documenting Resolution

When appropriate, leave a concise PR comment documenting the resolved findings.

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

After pushing fixes:

1. Check the current CI status.
2. If CI failed because of the changes, diagnose and fix the failure.
3. Run the relevant validation.
4. Push the fix.
5. Check CI again.
6. If CI is still running, report that status and stop.
7. Resume when invoked again and current results are available.

Do not asynchronously monitor CI.

Do not proceed to CodeRabbit while relevant CI is failing or still running.

Unrelated or pre-existing CI failures are not automatically Sourcery findings.

## Relationship With CodeRabbit

The normal review order is:

Sourcery, if available
→ resolve actionable findings
→ CI green
→ CodeRabbit full review
→ resolve actionable findings
→ CI green
→ CodeRabbit targeted follow-up

Sourcery findings should be resolved before the initial CodeRabbit review when a Sourcery review is available.

If no Sourcery review exists, proceed without blocking.

CodeRabbit remains the mandatory final automated review stage.

Do not create a Sourcery ↔ CodeRabbit feedback loop.

## Subsequent Changes

A Sourcery review covers the PR state available when Sourcery reviews it.

Subsequent material changes may result from:

- Sourcery findings.
- CodeRabbit findings.
- MegaLinter or other CI findings.
- Human review.
- Authorised changes.

Do not assume subsequent changes will receive another Sourcery review.

Material changes remain subject to the mandatory CodeRabbit process.

If material changes are made after CodeRabbit has reviewed the PR, follow the CodeRabbit follow-up process. Claude requests a targeted CodeRabbit review once CI is green.

Do not request another Sourcery review merely because changes were made.

Purely editorial or mechanical changes require no special Sourcery handling.

## When No Sourcery Review Exists

1. Check PR reviews and comments for `sourcery-ai`.
2. Confirm that no Sourcery review is available.
3. Do not wait for one.
4. Continue the normal CodeRabbit and repository review process.

Do not trigger an initial Sourcery review, work around Sourcery capacity limits, create special automation, or block the PR.

## Explicit Sourcery Re-Review Requests

Only request or perform a Sourcery re-review when the repository owner explicitly asks for one.

If an approved workflow exists and the owner requests it:

1. Assess the resulting review using this skill.
2. Fix valid findings.
3. Validate the changes.
4. Ensure branch currency.
5. Commit and push.
6. Document the resolution where appropriate.

A Sourcery re-review does not replace or alter the mandatory CodeRabbit process.

## Completion

The Sourcery stage is complete when:

1. Any available Sourcery review has been assessed.
2. Valid actionable findings have been resolved or disputed findings have been escalated to the owner.
3. Relevant validation has passed.
4. The branch is current.
5. Relevant CI is green before proceeding to CodeRabbit.
6. If no Sourcery review exists, the PR has not been blocked waiting for one.
7. The PR is ready for the mandatory CodeRabbit review.

The repository owner remains the final gatekeeper.

Do not merge unless explicitly instructed.

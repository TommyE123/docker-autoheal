---
name: sourcery-review
description: Handle Sourcery's secondary automatic PR review process. Use when a Sourcery review exists on a PR, or when checking whether one exists. Sourcery is a secondary reviewer alongside CodeRabbit and is not normally a merge gate.
---

# Sourcery Review

## Purpose

Sourcery is a secondary automated reviewer alongside CodeRabbit.

CodeRabbit remains the repository's mandatory PR review process.

Sourcery reviews eligible pull requests automatically through its GitHub App when review capacity is available.

A missing Sourcery review is not, by itself, a reason to block a pull request.

Do not use Sourcery as a replacement for CodeRabbit.

## Review Model

The expected workflow is:

```text
automatic review
→ assess findings
→ fix valid findings
→ targeted validation
→ CI
→ stop
```

Do not create automated coordination, dependencies, or feedback loops between Sourcery and CodeRabbit.

Sourcery does not normally require a re-review after fixes.

## Before Considering the Review Complete

Sourcery should normally be considered after the CodeRabbit review cycle has completed and the PR is otherwise ready for merge.

1. Check whether Sourcery has reviewed the current PR state.
2. If a review exists, read and assess it.
3. If no review exists, continue with the normal repository process.
4. Before the PR is ready for merge, ensure relevant CI/checks are green.
5. Do not manually trigger an initial Sourcery review.

The verified review author is:

```text
sourcery-ai
```

Do not search for:

```text
sourcery-ai[bot]
```

Check both PR reviews and PR comments when determining whether a Sourcery review exists.

## Assessing Findings

When Sourcery has reviewed the PR:

1. Read the complete review.
2. Assess each finding against the actual code and PR scope.
3. Use `REVIEW.md` as the repository-specific review standard.
4. Treat a review with no actionable findings as a valid outcome.
5. Treat only valid, actionable, PR-related findings as requiring action.

Ignore or explain findings that are:

* Incorrect.
* Pre-existing and unrelated to the PR.
* Speculative without a credible failure path.
* Purely stylistic.
* Already covered by existing automated tooling without a distinct issue.
* Outside the scope of the PR.

Do not manufacture additional findings or perform a broader repository audit.

## Fixing Actionable Findings

For each valid, actionable, PR-related finding:

1. Confirm the reported behaviour from the actual code.
2. Determine whether the PR introduced or materially worsened the issue.
3. Make the smallest appropriate change.
4. Keep the fix within the PR scope.
5. Do not suppress or work around a valid finding without a sound technical reason.

Do not make a change solely because Sourcery reported it.

If Sourcery reports that review capacity has been exhausted, take no further action and continue with the normal review process.

## Validation

Run the smallest relevant tests or checks that provide confidence in the fix.

Follow `.claude/rules/testing.md`.

Do not claim checks were run unless they were actually run.

## Branch Currency

Before the final review-fix commit and push:

1. Ensure the branch satisfies `.claude/rules/branch-currency.md`.
2. If the branch needs updating, resolve conflicts carefully.
3. Re-run relevant validation after any required branch update.

## Commit and Push

* Follow the repository's normal commit conventions.
* Keep review-fix commits focused.
* Push the changes to the PR branch.

## Document the Resolution

Post a concise PR comment describing the actionable findings addressed.

For example:

```text
Addressed the actionable Sourcery findings from the latest review:

- Fixed "<finding>" in "<file>".
- Fixed "<finding>" in "<file>".

Targeted validation completed: "<checks>".
```

Only mention a branch update if the branch was actually updated.

## CI

After pushing review fixes:

1. Allow relevant checks to complete.
2. Resolve failures caused by the review fixes.
3. Do not treat unrelated or pre-existing failures as review findings.

## Subsequent Changes

A Sourcery review covers the PR state available when that review runs.

Subsequent material changes may result from:

* Sourcery findings.
* CodeRabbit findings.
* MegaLinter findings.
* Human reviewer feedback.
* Additional authorised changes.

Do not assume those changes will receive another Sourcery review.

Material changes remain subject to the mandatory CodeRabbit review process.

If a material change is made after CodeRabbit has reviewed the PR, allow the normal automatic CodeRabbit review cycle to cover the updated PR state.

Do not create a Sourcery → CodeRabbit or CodeRabbit → Sourcery review dependency.

Purely editorial or mechanical changes that cannot affect behaviour, configuration, tests, workflows, or meaningful project guidance do not require special Sourcery handling.

## When No Sourcery Review Exists

If an eligible PR has no Sourcery review:

1. Check the PR reviews and comments for `sourcery-ai`.
2. Confirm that no Sourcery review exists.
3. Continue with the normal CodeRabbit process and repository checks.

Do not:

* Trigger a first review.
* Attempt to work around review capacity limits.
* Create special automation to force a review.
* Block the PR solely because Sourcery has not reviewed it.

## Explicit Sourcery Re-Review Requests

Only perform a Sourcery re-review when the repository owner explicitly requests one.

If an approved repository workflow for requesting a re-review already exists and the repository owner has explicitly requested one, that workflow may be used.

Assess the resulting review using this skill:

1. Fix valid, actionable findings.
2. Run targeted validation.
3. Ensure branch currency.
4. Commit and push the fixes.
5. Document the changes in the PR discussion.

Do not request another Sourcery review afterwards unless the repository owner explicitly requests one again.

## Completion Criteria

The Sourcery review stage is complete when:

1. Any existing Sourcery review has been assessed.
2. Valid, actionable Sourcery findings have been resolved.
3. Relevant validation has passed.
4. The branch satisfies repository currency requirements.
5. CI is green.
6. Any material changes are covered by the normal CodeRabbit process.

If no Sourcery review exists, do not block the PR solely because of the missing review.

The repository owner remains the final gatekeeper.

## Do Not Merge

Do not merge the PR unless instructed to do so.

---
name: coderabbit-review
description: Handle the repository's mandatory CodeRabbit review process for a substantive PR. Use when a PR reaches the CodeRabbit review stage before the repository owner merges it. CodeRabbit reviews eligible PRs automatically; this skill defines how to check, assess, fix, and follow up on those reviews. Do not perform an ad-hoc CodeRabbit review.
---

# CodeRabbit Review

## Purpose

CodeRabbit is the repository's mandatory automated PR review process.

Every substantive PR targeting `main` must receive a CodeRabbit review before the repository owner merges it.

The initial review is automatic. Do not post `@coderabbitai full review` to trigger the initial review.

Use this skill to assess CodeRabbit's review and manage any resulting fixes.

## Review Model

The expected workflow is:

```text
automatic review
→ assess findings
→ fix valid findings
→ targeted validation
→ CI
→ automatic incremental review
→ repeat if needed
```

Do not perform a separate ad-hoc CodeRabbit review.

The repository owner remains the final gatekeeper.

## Before Considering the Review Complete

1. Ensure the PR targets `main`.
2. Ensure the PR is in a suitable state for review.
3. Check whether CodeRabbit has reviewed the current PR state.
4. Read and assess the review when available, even if other CI checks are still running.
5. Before the PR is ready for merge, ensure relevant CI/checks are green.
6. Do not manually trigger a duplicate review.

If an eligible PR has not been reviewed automatically, check:

1. The PR target branch.
2. The PR status and current commit.
3. Whether CodeRabbit has already reviewed the current PR state.
4. The repository CodeRabbit configuration.
5. Any obvious reason the automatic review may not have run.

Do not immediately post `@coderabbitai full review`.

## Assessing Findings

When CodeRabbit has reviewed the PR:

1. Read the complete review.
2. Assess each finding against the actual code and PR scope.
3. Use `REVIEW.md` as the repository-specific review standard.
4. Treat a GREEN review as a valid outcome.
5. Treat only valid, actionable, PR-related findings as requiring action.

Ignore or explain findings that are:

- Incorrect.
- Pre-existing and unrelated to the PR.
- Speculative without a credible failure path.
- Purely stylistic.
- Already covered by existing automated tooling without a distinct issue.
- Outside the scope of the PR.

Do not manufacture additional findings or perform a general repository audit.

## Fixing Actionable Findings

For each valid, actionable, PR-related finding:

1. Confirm the reported behaviour from the actual code.
2. Determine whether the PR introduced or materially worsened the issue.
3. Make the smallest appropriate change.
4. Keep the fix within the PR scope.
5. Do not suppress, disable, or work around a valid finding without a sound technical reason.

Do not make a change solely because CodeRabbit reported it.

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

- Follow the repository's normal commit conventions.
- Keep review-fix commits focused.
- Push the changes to the PR branch.

## Document the Resolution

Post a concise PR comment describing the actionable findings addressed.

For example:

```text
Addressed the actionable CodeRabbit findings from the latest review:

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

A CodeRabbit review covers the PR state available when that review runs.

Material changes made afterwards remain subject to the normal CodeRabbit review cycle, including changes resulting from:

- CodeRabbit findings.
- Sourcery findings.
- MegaLinter findings.
- Other reviewer findings.
- Additional changes to the original task.
- Other authorised changes to the PR.

Allow the automatic incremental review mechanism to cover those changes.

Purely editorial or mechanical changes that cannot affect behaviour, configuration, tests, workflows, or meaningful project guidance do not require another review unless the repository owner explicitly requests one.

Do not manually request a duplicate full review when the automatic mechanism can cover the changed PR state.

## When Automatic Review Does Not Appear

If an eligible PR has no CodeRabbit review:

1. Check that the PR targets `main`.
2. Check the PR status and current commit.
3. Check whether CodeRabbit has already reviewed the current PR state.
4. Check the repository CodeRabbit configuration.
5. Check for an obvious reason the automatic review has not run.

Do not create duplicate review requests.

A manual review request is only appropriate if the automatic mechanism cannot cover the PR state or the repository owner explicitly requests one.

## Completion Criteria

The CodeRabbit review stage is complete when:

1. The applicable CodeRabbit review has been received.
2. Valid, actionable PR-related findings have been fixed or otherwise resolved.
3. Relevant targeted validation has passed.
4. CI is green.
5. The latest material PR changes have been covered by the automatic CodeRabbit review cycle.
6. No unnecessary duplicate review has been requested.

The repository owner remains the final gatekeeper.

## Do Not Merge

Do not merge the PR unless instructed to do so.

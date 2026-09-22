---
name: coderabbit-review

description: Handle the repository's mandatory CodeRabbit review process for a substantive PR. Use after Sourcery has been addressed when a review is available, or proceed if no Sourcery review exists. The first CodeRabbit request must be a full review; subsequent requests must be targeted follow-ups covering changes made in response to the review.
---

# CodeRabbit Review

## Purpose

CodeRabbit is the repository's mandatory final automated PR review process.

Every substantive PR targeting `main` must receive a CodeRabbit review before the repository owner merges it.

CodeRabbit does not automatically review a PR when it is submitted. Claude is responsible for requesting the review at the appropriate stage.

The repository owner remains the final gatekeeper.

## Substantive PR

A substantive PR is one that changes or could affect:

- Application or library code.
- Infrastructure or Docker behaviour.
- Tests or test behaviour.
- CI/CD, build, or release logic.
- Workflows or automation.
- Security or dependency configuration.
- Other meaningful project behaviour or configuration.

PRs containing only documentation, comments, formatting, metadata, or similarly mechanical changes may not require CodeRabbit unless the repository owner explicitly requests a review.

## Review Model

The expected workflow is:

Sourcery review, if available
→ assess findings
→ fix valid findings
→ ensure branch is current
→ CI green
→ Claude requests `@coderabbitai full review`
→ assess findings
→ fix valid findings or ask user if disputed
→ push PR fix
→ check CI
→ if CI fails, fix and push
→ once CI is green, Claude requests `@coderabbitai` follow-up
→ assess follow-up findings
→ repeat if necessary
→ repository owner final review/merge

If no Sourcery review exists at the time of assessment, proceed without waiting for one.

Do not block the PR waiting for a Sourcery review.

The first CodeRabbit request must always be a full review.

Subsequent CodeRabbit requests must be targeted follow-ups.

Never request another full review.

## Before First CodeRabbit Review

Before requesting the initial review:

1. Confirm the PR targets `main`.
2. Confirm it is substantive, or that the owner explicitly requested CodeRabbit.
3. Check whether Sourcery has reviewed the PR.
4. If a Sourcery review exists, assess it and address valid findings.
5. If no Sourcery review exists, proceed without waiting.
6. Ensure the branch is current.
7. If the branch requires updating, update it and rerun affected validation.
8. Check the current CI status.
9. Proceed only when relevant CI checks are green.
10. Ensure there are no outstanding changes that have not been validated.
11. Request the initial CodeRabbit full review.

Do not request CodeRabbit before these prerequisites are satisfied.

## REVIEW.md

Use `REVIEW.md` as the repository-specific review standard.

`REVIEW.md` takes precedence over generic CodeRabbit recommendations where they conflict.

Findings must still be assessed against the actual code and PR scope.

## Initial CodeRabbit Review

Claude requests the first review only after the prerequisites above are satisfied:

```text
@coderabbitai full review
```

This is the only full CodeRabbit review request permitted for the PR.

## Assessing Findings

When CodeRabbit reviews the PR:

1. Read the complete review.
2. Assess each finding against the actual code and PR scope.
3. Apply `REVIEW.md`.
4. Treat a GREEN review as a successful review outcome.
5. Take no further CodeRabbit action unless subsequent material changes require review.
6. Only valid, actionable, PR-related findings require action.

Ignore findings that are:

- Incorrect.
- Pre-existing and not materially affected by the PR.
- Speculative without a credible failure path.
- Purely stylistic.
- Already covered by existing tooling without a distinct issue.
- Outside the PR scope.

Do not manufacture findings or turn the CodeRabbit review into a general repository audit.

## Fixing Findings

For each valid finding:

1. Confirm the reported behaviour.
2. Determine whether the PR introduces or materially worsens the issue.
3. Make the smallest appropriate fix.
4. Keep the fix within the PR scope.
5. Follow `.claude/rules/testing.md`.
6. Ensure branch currency before pushing.
7. Commit and push the focused fix.

Do not change code solely because CodeRabbit suggested it.

## Disputed Findings

If Claude disagrees with a CodeRabbit finding:

- Do not change the code solely to satisfy CodeRabbit.
- Do not silently dismiss the finding.
- Present the owner with:
  - the finding;
  - Claude's assessment;
  - the relevant code or behaviour;
  - the specific reason for disagreement;
  - supporting evidence or validation.

The repository owner decides whether a disputed finding should be fixed or otherwise addressed.

## Validation and CI

After making fixes:

1. Run the smallest relevant validation required by `.claude/rules/testing.md`.
2. Do not claim checks were run unless they were actually run.
3. Commit and push the validated fix.
4. Check the current CI status.
5. If CI failed because of the changes, diagnose and fix the failure.
6. Rerun relevant validation.
7. Push the fix.
8. Check CI again.
9. If CI is still running, report that status and stop.
10. Resume when invoked again and current results are available.

Do not asynchronously monitor CI.

Do not request a CodeRabbit follow-up while relevant CI is failing or still running.

## Follow-Up Review

After valid findings have been addressed, changes have been pushed, and relevant CI is green, request a targeted follow-up review.

Use a message such as:

```text
@coderabbitai

Addressed the actionable findings from the previous review:

- Fixed "<finding>" in `<file>`.
- Fixed "<finding>" in `<file>`.

Validation completed:
- <checks>

CI is green.

Please perform a follow-up review of these changes and any directly affected code.
```

Do not request another full review.

The follow-up should focus on the changes made in response to the previous review and directly affected code.

## Subsequent Findings

For findings from a CodeRabbit follow-up:

1. Assess them against the actual code and PR scope.
2. Fix valid findings or escalate disputed findings.
3. Run relevant validation.
4. Ensure branch currency before pushing.
5. Commit and push.
6. Check CI.
7. If CI fails because of the changes, diagnose and fix it.
8. If CI is still running, stop and report.
9. Once CI is green, request another targeted CodeRabbit follow-up if further material changes require review.

Never request another full review.

Continue until there are no unresolved actionable findings and the repository owner is satisfied.

## Branch Currency

Before each review-fix push:

1. Follow `.claude/rules/branch-currency.md`.
2. Update the branch if required.
3. Rerun affected validation after the update.

The branch must also be current before the initial CodeRabbit review.

Only mention a branch update if the branch was actually updated.

## Review Scope

CodeRabbit reviews the PR state available when the review is requested.

Material changes made afterwards may result from:

- Sourcery findings.
- CodeRabbit findings.
- MegaLinter or other CI findings.
- Human review.
- Authorised changes.
- Additional task requirements.

Subsequent material changes remain subject to the CodeRabbit follow-up process.

Do not turn the review into a general repository audit or manufacture changes simply to obtain another review.

## Completion

The CodeRabbit review process is complete when:

1. Any available Sourcery review has been assessed and valid findings resolved.
2. The branch is current.
3. Relevant CI is green before the initial CodeRabbit review.
4. The initial full CodeRabbit review has been requested.
5. Valid CodeRabbit findings have been resolved.
6. Disputed findings have been escalated to the owner.
7. Relevant validation has passed.
8. CI is green after fixes.
9. All latest material changes requiring CodeRabbit review have been covered by the applicable review or targeted follow-up.
10. No unnecessary full review has been requested.
11. There are no unresolved actionable findings.
12. The repository owner is satisfied with the result.

Do not merge unless explicitly instructed.

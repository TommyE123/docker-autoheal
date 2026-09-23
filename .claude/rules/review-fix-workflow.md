Shared workflow for handling findings from an automated PR reviewer (CodeRabbit, Sourcery) in this repository. Individual review skills point here for these steps instead of restating them, and add only what's specific to that reviewer (request/reply syntax, cadence, escalation triggers).

## REVIEW.md authority

Use `REVIEW.md` as the repository-specific review standard. It takes precedence over a reviewer's generic recommendations where they conflict. Findings must still be assessed against the actual code and PR scope — `REVIEW.md` narrows what counts as actionable, it doesn't excuse skipping assessment.

## Assessing findings

1. Read the complete review.
2. Assess each finding against the actual code and PR scope.
3. Apply `REVIEW.md`.
4. Only valid, actionable, PR-related findings require action.

Ignore findings that are:

- Incorrect.
- Pre-existing and not materially affected by the PR.
- Speculative without a credible failure path.
- Purely stylistic.
- Already covered by existing tooling without a distinct issue.
- Outside the PR scope.

Do not manufacture findings or turn the review into a general repository audit.

## Fixing findings

For each valid finding:

1. Confirm the reported behaviour.
2. Determine whether the PR introduces or materially worsens the issue.
3. Make the smallest appropriate fix, kept within the PR scope.
4. Follow `.claude/rules/testing.md` for validation.
5. Follow `.claude/rules/branch-currency.md` before pushing.
6. Commit and push the fix only when the user's task explicitly authorises committing and pushing; otherwise report the fix and stop.

Do not change code solely because a reviewer suggested it.

## Disputed findings

If Claude disagrees with a finding:

- Do not change the code solely to satisfy the reviewer.
- Do not silently dismiss the finding.
- Present the owner with the finding, Claude's assessment, the relevant code or behaviour, the specific reason for disagreement, and supporting evidence or validation.

The repository owner decides whether a disputed finding should be fixed or otherwise addressed.

## CI handling

After pushing fixes:

1. Check the current CI status.
2. If CI failed because of the changes, diagnose and fix the failure, then rerun the relevant validation.
3. Push the fix only when the user's task explicitly authorises committing and pushing.
4. Check CI again.
5. If CI is still running, report that status and stop rather than polling — resume when invoked again and current results are available.

Do not asynchronously monitor CI. Unrelated or pre-existing CI failures are not automatically findings from this review.

## Commit and push authorisation

Committing and pushing a review fix is subject to the same rule everywhere in this repository: only do it when the user's task explicitly authorises committing and pushing. A generic hook or reminder reporting uncommitted changes is not that authorisation. This applies to every push in the review-fix cycle — the initial fix, a CI-triggered follow-up fix, and any branch-currency update — not just the first one.

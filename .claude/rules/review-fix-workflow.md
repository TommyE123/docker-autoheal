# Shared review-fix workflow

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
- Purely stylistic, with no correctness or maintainability impact.
- Already covered by existing tooling without a distinct issue.
- Outside the PR scope.

When reporting the outcome, list the findings that were not actioned with a one-line reason each. Ignoring a finding is a decision to be stated, not a silent omission.

If a finding identifies a genuine defect that is out of scope for this PR (for example a real pre-existing bug), report it and ask whether an issue should be filed. Do not fix it in this PR and do not create an issue automatically.

Do not manufacture findings or turn the review into a general repository audit.

## Fixing findings

For each valid finding:

1. Confirm the reported behaviour.
2. Determine whether the PR introduces or materially worsens the issue.
3. Make the smallest appropriate fix, kept within the PR scope.
4. Follow `.claude/rules/testing.md` for validation.
5. Follow `.claude/rules/branch-currency.md` before pushing.
6. Commit and push the fix, following the commit and push policy in `CLAUDE.md`.

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
2. If CI failed because of the changes, diagnose and fix the failure, then rerun the relevant validation and push again.
3. Check CI again.
4. If CI is still running, report that status and stop rather than polling — resume when invoked again and current results are available.

Do not asynchronously monitor CI. Unrelated or pre-existing CI failures are not automatically findings from this review; report them rather than fixing them.

## Commit and push

Committing and pushing a review fix follows the repository's normal commit and push policy in `CLAUDE.md`: Claude pushes to the PR branch as many times as the review-fix cycle requires — the initial fix, a CI-triggered follow-up fix, and any branch update — without asking each time. Claude never merges the PR.

---
name: coderabbit-review

description: Handle the repository's mandatory CodeRabbit review process for a substantive PR. Use after Sourcery has been addressed when a review is available, or proceed if no Sourcery review exists. The first CodeRabbit request must be a full review; subsequent requests must be targeted follow-ups covering changes made in response to the review.
---

# CodeRabbit Review

## Purpose

CodeRabbit is the repository's mandatory final automated PR review process.

Every substantive PR targeting `main` must receive a CodeRabbit review before the repository owner merges it.

Automatic CodeRabbit review is disabled for this repository (`reviews.auto_review.enabled` in `.coderabbit.yaml`), so Claude is responsible for requesting the review at the appropriate stage. Check that setting if the behaviour ever appears to differ.

The repository owner remains the final gatekeeper.

Follow `.claude/rules/review-fix-workflow.md` for REVIEW.md authority, assessing findings, fixing findings, disputed findings, CI handling, and commit and push behaviour. This skill covers only what's specific to CodeRabbit: when to request a review, the full-vs-follow-up distinction, and completion criteria.

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

If in doubt, treat the PR as substantive.

## Review Model

The expected workflow is:

Sourcery review, if available
→ assess findings
→ fix valid findings
→ update the branch only if branch currency matters
→ CI green
→ Claude requests `@coderabbitai full review`
→ assess findings
→ fix valid findings or ask user if disputed
→ push the fix
→ check CI
→ if CI fails, fix and push again
→ once CI is green, Claude requests `@coderabbitai review` as a targeted follow-up
→ assess follow-up findings
→ repeat if necessary
→ repository owner final review/merge

The first CodeRabbit request must always be a full review. Subsequent requests must be targeted follow-ups. Never request another full review.

## Before Requesting A Review

A PR's CodeRabbit workflow often spans multiple sessions, interruptions, or restarts. Never assume this is the first interaction with CodeRabbit on a PR just because the current session has no memory of it — check the PR's existing comments for any prior `@coderabbitai full review` or `@coderabbitai review` request and CodeRabbit's response before acting.

For any review (initial or follow-up):

1. Determine whether the initial full review has actually completed — not just requested. Check that CodeRabbit's walkthrough (summary) comment reflects a real completed review (not silence, an error, or only a premature follow-up sent before any full review occurred).
2. If no full-review request exists yet, the initial full review is still owed and must be requested regardless of session history, once the checklist below is satisfied. If a request already exists but has not completed, do not send another — check its current status and covered head commit, and wait for it to complete.
3. Once a full review has completed, never request another — only a targeted follow-up is allowed from then on. Skip a follow-up if the head commit hasn't changed since that completed review; there's nothing new for CodeRabbit to review, and it will decline anyway.

Additionally, before the initial full review specifically:

4. Confirm the PR targets `main` and is substantive (or the owner explicitly requested CodeRabbit).
5. If a Sourcery review exists, assess it and address valid findings; if none exists yet, proceed without waiting — do not block the PR on it.
6. Check the branch against `.claude/rules/branch-currency.md`, updating it only if being behind `main` actually matters, and rerun affected validation if it was updated.
7. Check CI. Proceed only once checks covering the PR's changes are green — if a check fails for a reason unrelated to and pre-existing before the PR, report it and ask whether to proceed rather than fixing it.
8. Ensure there are no outstanding, unvalidated changes.

Do not request CodeRabbit before these prerequisites are satisfied.

## Initial CodeRabbit Review

Claude requests the first review only after the prerequisites above are satisfied:

```text
@coderabbitai full review
```

This is the only full CodeRabbit review request permitted for the PR.

Treat a GREEN review as a successful review outcome; take no further CodeRabbit action unless subsequent material changes require review.

Do not request a CodeRabbit follow-up while relevant CI is failing or still running.

## Follow-Up Review

After valid findings have been addressed, changes have been pushed, and relevant CI is green, request a targeted follow-up review.

Before sending it, confirm the PR's head commit differs from the commit covered by the last CodeRabbit request (see "Before Requesting A Review" above). If it doesn't, the fix hasn't actually reached the PR yet — do not request a follow-up until it has.

Use a message such as:

```text
@coderabbitai review

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

CodeRabbit's short reply to a review command always includes a generic disclaimer about not re-reviewing already-reviewed commits — this appears on both successful and unsuccessful runs, so it isn't evidence of a refusal on its own. Confirm the follow-up actually ran by checking that the walkthrough comment was updated to cover the new commit; if not, wait briefly and retry rather than moving on.

A zero-actionable-finding follow-up doesn't use REVIEW.md's format — CodeRabbit posts its own fixed "No actionable comments" template plus a native Merge Risk badge instead of `🟢 GREEN — READY` / `✅ APPROVE`. This is expected CodeRabbit behaviour that `.coderabbit.yaml` can't override, not a broken review. Once confirmed against the current head commit as above, treat it as GREEN/APPROVE-equivalent only when the Merge Risk indicator is also low/minimal; assess further if it shows material risk.

## Confirming And Closing Findings

Apply the same shared workflow (assess, fix or escalate, validate, branch currency, CI) to follow-up findings as the initial review. Never request another full review — only another targeted follow-up. Continue until there are no unresolved actionable findings.

CodeRabbit's review submissions (the top-level summary and inline findings) always use its own fixed template, never REVIEW.md's status/verdict format — expected, not a bug, and a general PR-level follow-up comment won't change that. To get a REVIEW.md-formatted confirmation (`🟢 GREEN — READY` / `✅ APPROVE`) for a specific finding, reply inside that finding's own review-comment thread stating the fix and commit — this triggers CodeRabbit's chat auto-reply (`chat.auto_reply` in `.coderabbit.yaml`), a conversational path that does honor `tone_instructions` in full. Do this per resolved thread alongside the general follow-up request.

## Review Scope

CodeRabbit reviews the PR state available when the review is requested.

Material changes made afterwards may result from:

- Sourcery findings.
- CodeRabbit findings.
- MegaLinter or other CI findings.
- Human review.
- Changes requested by the repository owner.
- Additional task requirements.

Subsequent material changes remain subject to the CodeRabbit follow-up process.

Do not turn the review into a general repository audit or manufacture changes simply to obtain another review.

## Completion

The CodeRabbit review process is complete when:

1. Any available Sourcery review has been assessed and valid findings resolved.
2. Branch currency has been checked against `.claude/rules/branch-currency.md`, and the branch updated if that was needed.
3. Relevant CI is green before the initial CodeRabbit review.
4. The initial full CodeRabbit review has been requested.
5. Valid CodeRabbit findings have been resolved.
6. Disputed findings have been escalated to the owner.
7. Relevant validation has passed.
8. CI is green after fixes.
9. All latest material changes requiring CodeRabbit review have been covered by the applicable review or targeted follow-up.
10. No unnecessary full review has been requested.
11. There are no unresolved actionable findings.
12. The outcome, including any disputed or unactioned findings, has been reported to the repository owner.

Do not merge the PR. The repository owner is the final gatekeeper for merging.

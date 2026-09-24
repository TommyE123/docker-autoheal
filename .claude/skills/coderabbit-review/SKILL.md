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

If no Sourcery review exists at the time of assessment, proceed without waiting for one.

Do not block the PR waiting for a Sourcery review.

The first CodeRabbit request must always be a full review.

Subsequent CodeRabbit requests must be targeted follow-ups.

Never request another full review.

## Resuming Work On A PR

A PR's CodeRabbit workflow often spans multiple sessions, interruptions, or restarts. Never assume this is the first interaction with CodeRabbit on a PR just because the current session has no memory of it.

Before requesting any CodeRabbit review (initial or follow-up):

1. Check the PR's existing comments for any prior `@coderabbitai full review` or `@coderabbitai review` request and CodeRabbit's response.
2. If a full review has already been requested for this PR (in this session or a prior one), never request another full review — only a targeted follow-up is allowed from this point on.
3. Identify the commit the most recent CodeRabbit request covered, and compare it to the PR's current head commit.
4. If the head commit has not changed since the last CodeRabbit request, do not request another review — there is nothing new for CodeRabbit to review, and it will decline anyway.

Only request a follow-up when the head commit has changed since the last CodeRabbit request and relevant CI is green for that commit.

## Before First CodeRabbit Review

Before requesting the initial review:

1. Confirm the PR targets `main`.
2. Confirm it is substantive, or that the owner explicitly requested CodeRabbit.
3. Check whether Sourcery has reviewed the PR.
4. If a Sourcery review exists, assess it and address valid findings.
5. If no Sourcery review exists, proceed without waiting.
6. Check the branch against `.claude/rules/branch-currency.md`, and update it only if being behind `main` actually matters.
7. If the branch was updated, rerun affected validation.
8. Check the current CI status.
9. Proceed only when the CI checks covering the PR's changes are green. If a check is failing for a reason unrelated to and pre-existing before the PR, do not try to fix it — report it and ask whether to proceed.
10. Ensure there are no outstanding changes that have not been validated.
11. Request the initial CodeRabbit full review.

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

Before sending it, confirm the PR's head commit differs from the commit covered by the last CodeRabbit request (see "Resuming Work On A PR" above). If it doesn't, the fix hasn't actually reached the PR yet — do not request a follow-up until it has.

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

CodeRabbit's short reply to a review command always includes a generic disclaimer about not re-reviewing already-reviewed commits — this text appears on both successful and unsuccessful runs and is not on its own evidence of a refusal. To confirm whether the follow-up actually ran, check whether CodeRabbit's walkthrough (summary) comment on the PR was updated after the follow-up request, covering a commit range that includes the new fix commit. If it was not updated and the reply gives no other indication of a completed review, treat the follow-up as not completed: re-check the head commit, wait briefly, and retry rather than silently moving on.

### Zero-actionable-finding outcomes

When CodeRabbit's follow-up genuinely runs and finds nothing to flag, it does not use REVIEW.md's format — it posts its own fixed template in the walkthrough comment (e.g. "No actionable comments were generated in the recent review. 🎉") alongside its own built-in Merge Risk badge, instead of REVIEW.md's `🟢 GREEN — READY` / `✅ APPROVE`. This is a CodeRabbit product behaviour that `.coderabbit.yaml` cannot override, not a broken or incomplete review. Treat this native "no actionable comments" outcome, once confirmed against the current head commit as above, as equivalent to a GREEN/APPROVE review — do not request another review solely because the wording doesn't match REVIEW.md.

## Subsequent Findings

For findings from a CodeRabbit follow-up, apply the same shared workflow (assess, fix or escalate, validate, branch currency, CI) as the initial review. Never request another full review — only another targeted follow-up. Continue until there are no unresolved actionable findings.

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

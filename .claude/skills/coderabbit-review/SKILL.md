---
name: coderabbit-review
description: "Use only when the user asks, after pushing a substantive PR to `main`: wait for green PR checks, request CodeRabbit reviews by GitHub comment, fix in-scope findings, and report blockers without monitoring indefinitely."
---

# CodeRabbit PR Review

Run this only when the user tells you to, for a pushed substantive PR targeting `main`. GitHub automatic reviews stay disabled. Never merge; the owner decides.

## Ground rules

- Never post `@coderabbitai full review` or `@coderabbitai review`, including follow-up reviews after fix pushes, unless the user has told you to. Without that instruction, stop and report that no CodeRabbit review has been requested.
- All evidence must be for the current pushed head (`gh pr view <PR> --json headRefOid`). Recheck the head and its checks immediately before requesting a review or reporting the PR ready. If the head changed, go back to the CI gate.
- A verified, intentionally skipped job (such as the Docker smoke test on a fork PR) is not applicable, not passing. Investigate any unexpected skipped, neutral, or missing check.
- Read new PR comments and submitted reviews from people and bots. Act on actionable in-scope feedback. Don't treat every suggestion as a required fix, and don't wait for reviewers who haven't commented.
- Respect no-commit and no-push instructions. Without a new pushed head, stop before any PR reply or review request.
- Don't resolve threads automatically, keep a review database, or post about rate limits on the PR. Report blockers privately to the user.

## 1. CI gate (per pushed head)

1. Confirm the PR targets `main`, the head is pushed, and GitHub access works. Follow `.claude/rules/branch-currency.md` only when being behind `main` matters.
2. Run `gh pr checks <PR>`. While checks are pending, `sleep 60` and run it again, at most 10 times per pushed head.
3. Every applicable check must pass.
4. Inspect MegaLinter findings even if its job passed. Fix findings this PR introduced or worsened, including nonblocking warnings, under `.claude/rules/megalinter.md`. Leave unrelated pre-existing findings alone. If you can't classify a warning, compare narrowly against `main` or available pre-PR results. If the baseline is still unclear, report that and stop.
5. Fix in-scope CI failures, run targeted validation for each fix, and push under `CLAUDE.md`.
6. Make at most two CI fix-and-push rounds per invocation. Rounds after CodeRabbit fixes count towards the two.

Report the blocker to the user and stop, without requesting a review, in any of these cases:

- Checks are still pending after 10 attempts.
- An unrelated failure blocks green CI.
- The same failure persists after a fix.
- Anything PR-related is unresolved after two rounds.

## 2. Request a review

- Check existing requests and CodeRabbit responses first. Don't duplicate an active request or one already covering the current head.
- If no full review has completed, post a top-level PR comment: `@coderabbitai full review`.
- If a full review completed and a new head has been pushed since, post `@coderabbitai review` once all checks are green, but only if the user has told you to. Fixing findings from a completed review doesn't count as such an instruction.

## 3. Wait for the review

- Run `gh pr view <PR> --json reviews,comments` every 60 seconds, at most 10 times. You are looking for a CodeRabbit review of the requested head.
- These do not count as completion: an acknowledgment, silence, a skipped review, or a review of an older head. Re-read the bot's reply to your command each time, because an acknowledgment may be edited into a rate-limit notice.
- If a review arrives, report that CodeRabbit reviewed that head and what it found. That alone doesn't make the PR ready.
- If you are rate limited, stop immediately. Don't retry and don't comment on the PR.
- If the review is still pending after 10 checks, stop without sending another request. Silence is not failure: CodeRabbit can take 15 minutes or more, so report it as "not received yet", never as "never reviewed".
- Re-read the PR's reviews and comments immediately before reporting, in case the review landed after your last check. This final read doesn't count towards the 10 checks.
- In both stop cases, report "review not completed" and the reason to the user.

## 4. Handle findings

1. Read inline comments with `gh api repos/<owner>/<repo>/pulls/<PR>/comments --paginate`; `gh pr view` does not return them. The endpoint also returns older reviews and replies, so keep top-level comments (no `in_reply_to_id`) and skip only threads already handled (resolved, or answered with the fix and its commit). The REST comments don't say whether a thread is resolved. In Claude Code cloud sessions, where GraphQL returns a 403, read `resolved` from the session-provided route `gh api repos/<owner>/<repo>/pulls/<PR>/ccr/review_threads` (it is not part of GitHub's REST API). It returns one entry per thread with `comment_ids` (the REST comment IDs), `resolved`, `outdated`, `path` and `line`; find the thread whose `comment_ids` contains the top-level comment's `id`. Elsewhere, use `gh api graphql` selecting `reviewThreads(first: 100) { nodes { isResolved comments(first: 1) { nodes { databaseId } } } }`, matched on the first comment's `databaseId`. Don't filter by `commit_id` alone: after a fix push, an unresolved finding from an earlier review that CodeRabbit doesn't repeat would be dropped. Verify each remaining finding against the current code. Assess each finding against the changed code and the Evidence Threshold and Scope and Noise sections of `REVIEW.md`.
2. The result is clean when three things are true: the review covers the current head, checks are still green, and no actionable in-scope findings remain. Then report the PR ready for the owner and stop. Don't post a fix reply or request a follow-up.
3. Otherwise, fix every confirmed in-scope finding and validate. A finding is confirmed when you've checked it against the code and agree the code has the reported defect, whatever severity CodeRabbit gave it. This includes nits: fix a nit you agree with rather than leave something not great in the code, but don't change code for a nit you don't agree with (see step 4). In scope means lines this PR changed. Report a nit about unrelated code to the user instead of fixing it. Make all fixes from one review in a single push.
4. For a disputed finding, don't change code just to satisfy CodeRabbit, and don't dismiss it silently. Reply once in its thread saying you disagree, with your assessment, the relevant code, and your evidence. Also list it in your report to the user.
5. After pushing fixes, repeat the CI gate for the new head.
6. Once green, reply once to each fixed finding in its thread with the fix and the pushed commit. If a finding has no thread, identify it in a PR comment. Every finding that gets changes requested ends with a reply saying what you did, whether you fixed it or disagreed. Don't request another review, and stop after replying.
7. After replying, wait 60 seconds, then read CodeRabbit's replies in the threads you answered. Don't reply again; report any that disagree or raise a new point.
8. Recheck the final head and its checks before reporting. Never start an unbounded fix/review loop.

## Owner change requests

An outstanding owner change request assigned to Claude supersedes any earlier clean-review handoff. When asked to address one:

1. Read the comment and the current head, and clarify any material ambiguity.
2. Implement only the requested change, with targeted validation.
3. Run the CI gate for the new head.
4. Reply once in the owner's inline thread, or post a PR comment linking their top-level request, with the fix and the pushed commit.
5. Don't request a CodeRabbit review unless the user tells you to.

The earlier clean review doesn't cover the new head.

## Resuming later

Inspect the head, checks, prior requests, replies, and CodeRabbit results afresh.

- If an earlier review completed late, handle its findings.
- If CodeRabbit is still actively reviewing, report it as pending and don't request again.
- If an earlier request was rate limited or stayed silent past the wait, and there's no sign of an active review, send one new request for the review still owed, but only if the user has told you to request a review. Otherwise, report that the review is still outstanding and don't post.
- A rate-limited full request means the first full review is still owed. A completed full review followed by a new head needs a follow-up only if the user asks for one.
- Don't duplicate replies, and don't request a review of an unchanged head that already has a completed review.

## Reporting

- List findings not actioned, each with a one-line reason.
- Report genuine out-of-scope defects and ask whether to file an issue. Don't fix them or create one.
- A clean CodeRabbit review posts its own "No actionable comments" message and a Merge Risk badge instead of the `REVIEW.md` format. That is expected, not a broken review. Once it's confirmed to cover the current head, treat it as clean only if Merge Risk is low or minimal. Otherwise, assess further before reporting the PR ready.

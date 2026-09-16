---
name: coderabbit-review
description: Request a CodeRabbit review on a substantive PR in this repository, once it is green and mergeable. Use whenever a PR reaches the point where it needs a CodeRabbit review before Tom merges it — this is the repository's mandatory, repo-specific CodeRabbit procedure and must be followed exactly rather than posting an ad-hoc review request.
---

# CodeRabbit review

Automatic reviews are off in `.coderabbit.yaml` (`reviews.auto_review.enabled: false`), so CodeRabbit reviews a PR only when it is explicitly asked. Every substantive PR gets a CodeRabbit review before Tom merges it.

**Ask only once the PR is green.** Wait until every check the PR triggers has passed and the branch has no merge conflict. Asking while CI is red spends the review on findings CI has already reported.

**Always use `@coderabbitai full review`, never `@coderabbitai review`.** `review` is incremental: with automatic reviews disabled it can reply "CodeRabbit is an incremental review system and does not re-review already reviewed commits" and do nothing, which has already happened on PR #105. `full review` reviews the whole PR from scratch.

Free-form instructions in the same comment as the command are honoured (`chat.auto_reply: true`), so put them directly under the command. Post the template below as a single PR comment, filling in **Context**, **In scope** and **Out of scope** and leaving the rest verbatim — the fixed **How to report** and **Verdict** sections are what make reviews comparable across PRs, so don't reword them per PR:

```markdown
@coderabbitai full review

**Context**
- PR #<N>: <title>
- Issue: Closes #<M>   <!-- or: none — <which linked-issue exception applies> -->
- Change type: <bug fix | feature | test-only | refactor | docs | ci/config | dependency>
- All checks green on <short-sha>.
- <1-3 lines: what changed and why. For a re-review, say what changed since the last round.>

**In scope**
- <the specific behaviour, file or path to verify — one bullet each>
- <any related PR/issue CodeRabbit must inspect before concluding, and why>

**Out of scope**
- Pre-existing MegaLinter findings unrelated to this PR, unless this PR introduced or worsened them.
- Codecov percentages as evidence of correctness.
- Style-only preferences and unrelated cleanup.

**How to report**
Inspect the surrounding repository, not just the changed lines. Do not treat the PR
description or a passing test suite as proof of correctness. Do not manufacture
findings — if the PR is correct, say so plainly.

Classify every finding as exactly one of:
- 🔴 **BLOCKER** — must be fixed before merge
- 🟠 **IMPORTANT** — significant correctness or regression risk
- 🟡 **MINOR** — worthwhile but not merge-blocking
- 🟢 **GOOD** — something the PR gets right, worth calling out

For each 🔴/🟠/🟡 finding give: exact `file:line`, what is wrong, why it matters, the
smallest correct fix, whether this PR introduced it or it is pre-existing, and whether
a regression test is required.

**Verdict**
End with exactly one of:
- ✅ **APPROVE** — safe to merge
- ⚠️ **APPROVE WITH MINOR CHANGES** — no blocking issue
- ❌ **CHANGES REQUIRED** — blocking issue found

Review only — do not push commits to this PR.
```

Keep **In scope** to the handful of things that actually need judgement; it is the only part that should grow, and a scope list longer than about ten bullets means the PR is too broad. After pushing review fixes, wait for green again and post a fresh `full review` comment whose Context says what changed since the last round.

## Handling actionable findings

When CodeRabbit reports findings:

1. **Investigate each finding** — determine whether it is valid and related to the PR. Invalid, pre-existing, or genuinely out-of-scope findings can be explained rather than fixed.
2. **Fix valid PR-related findings** — do not simply acknowledge and leave them unresolved. Do not suppress, disable, or work around a valid finding merely to obtain approval.
3. **Run appropriate targeted validation** — use the smallest relevant check for the changed behaviour. For guidance on validation scope, see `.claude/rules/testing.md`.
4. **Check if the PR branch is behind main** — before committing and pushing the fixes, verify that the PR branch is current with main. If it is behind, update the branch using the repository's established branch-update or rebase workflow, resolve any conflicts carefully, and re-run appropriate targeted validation. See `.claude/rules/branch-currency.md` for detailed guidance.
5. **Commit and push the fixes** — commit and push the completed, validated changes.
6. **Post a concise PR comment** explaining what CodeRabbit identified and what was fixed:
   ```
   Addressed the actionable CodeRabbit findings from the latest review:
   
   - Fixed "<finding>" in "<file>".
   - Fixed "<finding>" in "<file>".
   
   Targeted validation completed: "<checks>".
   
   The branch was updated from "main" before the fixes were committed/pushed.
   
   CI is now being allowed to return to green before requesting another full CodeRabbit review.
   ```
   Only mention the branch update when one actually occurred.
7. **Wait for checks to return to green** — do not request another review while CI is red.
8. **Request another full review** — post a fresh `@coderabbitai full review` comment.
9. **Repeat if necessary** — if the new review identifies further valid, PR-related actionable findings, go back to step 1.
10. **Stop when done** — when there are no further actionable findings, or when all remaining findings have been appropriately explained as invalid or out-of-scope, the cycle is complete.

Do not create an infinite review/fix loop. The purpose is to resolve genuine actionable findings, not repeatedly chase reviewer noise.

## CodeRabbit review after subsequent substantive changes

If Claude makes any substantive or material change to the PR after the most recent CodeRabbit full review, a fresh `@coderabbitai full review` must be requested once CI/checks are green, regardless of why the change was made.

Substantive/material changes include those made to address:
- Sourcery findings
- MegaLinter findings
- another reviewer's findings
- the original task
- other authorised PR work

**Exception:** Do not create a duplicate review if the current CodeRabbit fix/review cycle already requires another full review — that review satisfies this requirement and avoids unnecessary duplicate reviews.

**Exception:** Trivial-only changes such as wording, comments, formatting, or metadata changes that cannot affect behaviour, configuration, tests, workflows, or meaningful repository guidance do not require a fresh CodeRabbit review unless the task explicitly requests one.

Do not merge the PR yourself — see `CLAUDE.md`'s Merging section. Tom (@TommyE123) is the final gatekeeper.

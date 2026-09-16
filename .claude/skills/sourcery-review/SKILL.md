---
name: sourcery-review
description: How to treat Sourcery's automatic PR reviews in this repository, on top of the mandatory CodeRabbit review. Sourcery reviews PRs automatically via its installed GitHub App — this skill is about not disturbing that automation and not requesting unnecessary re-reviews, not about manually triggering a first review.
---

# Sourcery review

Sourcery is installed as a GitHub App and reviews PRs automatically — Claude does not need to (and should not try to) trigger a first review. It is independent of CodeRabbit, which remains the normal mandatory PR review process; do not make Sourcery a mandatory gate unless Tom explicitly requests it. Do not create automatic coordination or feedback loops between Sourcery and CodeRabbit.

- Do not disable, suppress, or otherwise manipulate Sourcery's automatic reviews.
- The verified GitHub review author is `sourcery-ai`. Do not use `sourcery-ai[bot]`. Check the PR's existing reviews/comments for a review by `sourcery-ai` before assuming none exists.
- An existing Sourcery review on a PR counts as *the* Sourcery review for that PR.
- After making fixes based on that review, do not automatically request a Sourcery re-review — a re-review is only requested when Tom explicitly asks for one.
- Do not create Sourcery → fix → Sourcery re-review loops.
- Do not attempt to determine, manage, or work around the account-wide Sourcery review budget.
- If Sourcery reports that its review budget is exhausted, do not attempt another review.
- Do not add labels, workflows, hooks, status checks, or other automation to control Sourcery.
- Do not reproduce Sourcery locally.

## Handling actionable findings

When Sourcery reports findings and you fix them:

1. **Fix valid, actionable findings** — integrate the changes into the PR.
2. **Run appropriate targeted validation** — use the smallest relevant check for the changed behaviour. For guidance on validation scope, see `.claude/rules/testing.md`.
3. **Check if the PR branch is behind main** — before committing and pushing the fixes, verify that the PR branch is current with main. If it is behind, update the branch using the repository's established branch-update or rebase workflow, resolve any conflicts carefully, and re-run appropriate targeted validation. See `.claude/rules/branch-currency.md` for detailed guidance.
4. **Commit and push the fixes** — commit and push the completed, validated changes.
5. **Post a concise PR comment** explaining what Sourcery identified and what was fixed:
   ```
   Addressed the actionable Sourcery findings:
   
   - Fixed "<finding>" in "<file>".
   - Fixed "<finding>" in "<file>".
   
   Targeted validation completed: "<checks>".
   ```
6. **Do not automatically request another review** — the cycle stops here. Sourcery re-review is only performed when Tom explicitly asks for it.

If Tom subsequently asks for a Sourcery re-review, follow the existing Sourcery workflow and update the PR discussion with the result. Do not create an automatic Sourcery fix/re-review loop.

## Boundary with CodeRabbit

```text
CodeRabbit → fix actionable findings → comment → green → request full re-review → repeat if needed
Sourcery   → fix actionable findings → comment → stop; Tom decides whether re-review is needed
```

Do not create automatic coordination loops or feedback dependencies between Sourcery and CodeRabbit (such as automated labels, workflows, or status checks that tie one to the other). However, when a Sourcery-driven material change is made to a PR that has previously received a CodeRabbit review, a fresh `@coderabbitai full review` remains required once CI returns to green (per the CodeRabbit workflow in `CLAUDE.md`). The requirement for fresh CodeRabbit reviews after material changes — including Sourcery-driven changes — overrides any notion of avoiding coordination.

Do not merge the PR yourself — see `CLAUDE.md`'s Merging section. Tom (@TommyE123) is the final gatekeeper.

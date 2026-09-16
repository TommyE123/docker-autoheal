---
name: sourcery-review
description: How to treat Sourcery's automatic PR reviews in this repository, on top of the mandatory CodeRabbit review. Sourcery reviews PRs automatically via its installed GitHub App — this skill is about not disturbing that automation and not requesting unnecessary re-reviews, not about manually triggering a first review.
---

# Sourcery review

Sourcery is installed as a GitHub App and reviews PRs automatically — Claude does not need to (and should not try to) trigger a first review. It is independent of CodeRabbit, which remains the normal mandatory PR review process; do not make Sourcery a mandatory gate unless Tom explicitly requests it, and do not chain the two together.

- Do not disable, suppress, or otherwise manipulate Sourcery's automatic reviews.
- The verified GitHub review author is `sourcery-ai`. Do not use `sourcery-ai[bot]`. Check the PR's existing reviews/comments for a review by `sourcery-ai` before assuming none exists.
- An existing Sourcery review on a PR counts as *the* Sourcery review for that PR.
- After making fixes based on that review, do not automatically request a Sourcery re-review — a re-review is only requested when Tom explicitly asks for one.
- Do not create Sourcery → fix → Sourcery re-review loops.
- Do not attempt to determine, manage, or work around the account-wide Sourcery review budget.
- If Sourcery reports that its review budget is exhausted, do not attempt another review.
- Do not add labels, workflows, hooks, status checks, or other automation to control Sourcery.
- Do not reproduce Sourcery locally.

## Boundary with CodeRabbit

```
CodeRabbit → normal mandatory PR review process
Sourcery   → automatic reviewer; re-review only on Tom's explicit request
```

Do not create a dependency such as CodeRabbit → Sourcery → CodeRabbit, and do not create automated review loops or add labels/status checks/workflows to coordinate the two.

Do not merge the PR yourself — see `CLAUDE.md`'s Merging section. Tom (@TommyE123) is the final gatekeeper.

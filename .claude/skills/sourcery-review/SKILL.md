---
name: sourcery-review
description: Optional second-opinion review of a PR in this repository using Sourcery, on top of the mandatory CodeRabbit review. Use only when explicitly requested or clearly valuable, and check first whether this PR already has a Sourcery review — it is a scarce resource and is normally spent at most once per PR.
---

# Sourcery review (optional)

Sourcery is an optional second opinion and a scarce resource. It is independent of CodeRabbit, which remains the normal mandatory PR review process — do not make Sourcery a mandatory gate unless Tom explicitly requests it, and do not chain the two together.

- Default to at most one Sourcery review per PR.
- Before invoking Sourcery, inspect the PR's existing reviews/comments for a prior Sourcery review.
- The verified GitHub review author is `sourcery-ai`. Do not use `sourcery-ai[bot]`.
- If a prior review by `sourcery-ai` exists, treat that PR's Sourcery review as already spent unless Tom explicitly asks for another.
- Do not create Sourcery → fix → Sourcery → fix loops.
- Large/complex PRs should normally receive one review only.
- Do not calculate or try to determine the account-wide Sourcery budget.
- Do not add labels, status checks, workflows, or other repository state solely to enforce this policy.
- Do not reproduce Sourcery locally.

## Boundary with CodeRabbit

```
CodeRabbit → normal mandatory PR review process
Sourcery   → optional second opinion
```

Do not create a dependency such as CodeRabbit → Sourcery → CodeRabbit, and do not create automated review loops or add labels/status checks/workflows to coordinate the two.

Do not merge the PR yourself — see `CLAUDE.md`'s Merging section. Tom (@TommyE123) is the final gatekeeper.

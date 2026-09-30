---
name: simplification-review
description: Review proposed Autoheal dependencies, workflows, automation, tooling, or infrastructure for simpler maintainable alternatives before implementation.
---

# Simplification Review

Use when a proposal adds or significantly changes dependencies, CI/CD, release/version automation, build/development tooling, configuration machinery, generic utilities, or repository infrastructure. This is an on-demand review, not a required phase for every change.

Before designing custom machinery, check in order: existing Autoheal code; existing dependencies; GitHub/GitHub Actions; Docker/Compose; the language/runtime standard library; established third-party tools/actions; whether the requirement can be simplified or removed; and only then custom code.

For non-trivial tooling choices, weigh maintenance burden, maturity, adoption, security, release activity, integration complexity, lock-in, and operational cost. Do not add a dependency merely to remove a small amount of code, or assume third-party software is automatically better. Recommend the smallest maintainable approach with a brief rationale and any material tradeoffs. Do not change files as part of this review.

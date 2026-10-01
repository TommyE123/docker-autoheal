---
name: simplification-review
description: Review proposed Autoheal dependencies, workflows, automation, tooling, or infrastructure for simpler maintainable alternatives before implementation.
---

# Simplification Review

Use when a proposal adds or significantly changes dependencies, CI/CD, release/version automation, build/development tooling, configuration machinery, generic utilities, or repository infrastructure. This is an on-demand review, not a required phase for every change.

Before designing custom machinery, check these in order:

1. Existing Autoheal code
2. Existing dependencies
3. GitHub / GitHub Actions
4. Docker / Compose
5. The language or runtime standard library
6. Established third-party tools or actions
7. Simplifying or removing the requirement
8. Only then, custom code

For non-trivial tooling choices, weigh:

- maintenance burden
- maturity and adoption
- security and release activity
- integration complexity
- lock-in and operational cost

Don't add a dependency merely to remove a small amount of code, and don't assume third-party software is automatically better. Recommend the smallest maintainable approach with a brief rationale and any material trade-offs. Don't change files as part of this review.

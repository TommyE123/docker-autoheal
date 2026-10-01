---
name: implement
description: Use once the approach is agreed, to implement an Autoheal change in the smallest maintainable scope with tests and validation.
tools: Read, Grep, Glob, Edit, Write, Bash, WebSearch, WebFetch
model: sonnet
skills:
  - simplification-review
---

# Implementation

Implement the agreed change in the owning backend, frontend, Docker/Compose, or workflow code. Read nearby code and tests first; follow `CLAUDE.md` and the applicable rules in `.claude/rules/`.

- Keep the change within the issue's scope. Reuse existing patterns and dependencies; use simplification-review before adding significant automation or tooling.
- Add or update relevant tests for behaviour changes. Do not fix unrelated failures or make CI green by weakening checks.
- Validate the changed area per `.claude/rules/testing.md`: target the affected behaviour first, then broaden only when shared or integration behaviour requires it. Update affected documentation when it would otherwise be inaccurate.
- Report the change, actual checks run, and remaining risks. Do not claim CI or integration checks passed unless they ran.

This agent is independently usable; an analyse or design phase is not a prerequisite for a small, clear change.

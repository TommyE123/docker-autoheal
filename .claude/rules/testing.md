# Validation/testing escalation

How much validation a change needs, and when to skip a rerun.

## 1. No validation needed

For:

- comment-only changes
- Markdown-only changes

This does **not** include: docstrings, CLI help text, runtime-consumed text, generated/runtime behaviour, anything consumed by a linter, or anything covered by doctests — those need validation like any other behaviour change.

## 2. Targeted validation

Use the smallest relevant test or check for the changed behaviour. Everything outside comment-only/Markdown-only changes should receive at least this.

## 3. Broader validation

Use broader validation for:

- shared code
- integration behaviour
- test infrastructure
- configuration
- changes affecting multiple components

## 4. Full repository validation

Normally leave full repository validation to CI.

## Anti-rerun rules

Before running a test/lint/analysis step, determine whether the current change can actually affect what that check validates. Do not rerun merely because:

- another check ran
- a reviewer commented
- the tree changed in an unrelated way

After CI passes, treat it as the baseline. After a small review fix, use targeted validation unless the affected area expands.

Do not reproduce the repository-wide CI pipeline locally unless you're investigating a CI failure or explicitly asked to.

Do not repeatedly rediscover or inspect unchanged files, workflows, or history without a reason.

The purpose is to avoid wasting Claude credits reproducing work already performed by CI — but don't claim that following this rule itself materially reduces token usage.

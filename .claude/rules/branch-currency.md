# Keeping the PR branch current with main

A PR branch being behind `main` is normal and usually harmless. Update it only when being behind actually matters.

## When to update the branch

Update the branch when any of these is true:

- GitHub reports a conflict with `main`.
- A required check or branch-protection rule requires the branch to be up to date before merging.
- The work depends on, or could be invalidated by, something that changed in `main` (for example the code being fixed was since modified, or CI on the branch is failing for a reason already fixed on `main`).

Otherwise leave the branch alone and let the merge bring `main` in. Do not update the branch merely because `main` has moved on.

## How to update the branch

This repository updates PR branches by merging `main` into the branch:

```bash
git fetch origin main
git merge origin/main
```

Use merge rather than rebase. It matches the repository's existing history and avoids rewriting pushed commits, so no force push is needed.

## After updating the branch

1. **Resolve any conflicts carefully** — do not automatically accept either side of a conflict. Understand what changed on main and how it relates to the PR's changes. Apply fixes appropriately.
2. **Re-run appropriate targeted validation** — after a branch update and conflict resolution, re-run the validation checks for the changed code to ensure the merge did not introduce issues.
3. **Push the result** — see the commit and push policy in `CLAUDE.md`.

## Do not over-update

Do not turn this into a separate polling or repeated branch-checking loop, and do not re-check currency on every push.

The purpose is to ensure fixes are based on a `main` they are still valid against — not to maintain ongoing synchronisation with `main` throughout the session.

## CI remains authoritative

After pushing, allow the normal CI/validation pipeline to run. CI provides the authoritative full validation; GitHub's branch-protection rules and PR state determine the final mergeability status.

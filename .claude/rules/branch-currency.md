# Keeping the PR branch current with main

When Claude is already working on a PR and preparing to commit and push completed changes, the PR branch should be current with main to ensure the fixes are based on the latest main.

## When to update the branch

Before the final validation and push of completed fixes, check whether the PR branch is behind main:

- If the branch is current with main, proceed with validation and push as normal.
- If the branch is behind main, update it before the final validation and push.

## How to update the branch

Use the repository's established branch-update or rebase workflow. This is typically:

```bash
git fetch origin main
git rebase origin/main
```

Or, depending on repository convention:

```bash
git fetch origin main
git merge origin/main
```

Check the repository's contribution guidelines or recent PR history for the established workflow.

## After updating the branch

1. **Resolve any conflicts carefully** — do not automatically accept either side of a conflict. Understand what changed on main and how it relates to the PR's changes. Apply fixes appropriately.
2. **Re-run appropriate targeted validation** — after a branch update and conflict resolution, re-run the validation checks for the changed code to ensure the merge/rebase did not introduce issues.
3. **Proceed with the final push** — once validation passes after the branch update, commit (if needed after rebase) and push.

## Do not over-update

Do not perform unnecessary branch updates when the branch is already current with main.

Do not turn this into a separate polling or repeated branch-checking loop.

The purpose is to ensure the fixes being pushed and subsequently reviewed are based on the current main, not to maintain ongoing synchronization with main throughout the session.

## CI remains authoritative

After pushing, allow the normal CI/validation pipeline to run. CI provides the authoritative full validation; GitHub's branch-protection rules and PR state determine the final mergeability status.

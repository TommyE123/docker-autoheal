# MegaLinter finding handling

How to handle MegaLinter failures and findings in pull requests.

## When MegaLinter fails

MegaLinter is configured in `.mega-linter.yml` and runs as part of CI. When a PR triggers MegaLinter failures:

1. **Inspect the reported findings** — read the MegaLinter check output to identify what failed and why.
2. **Categorize each finding** — determine whether it is:
   - Introduced by the PR (new code added in this PR violates the rule)
   - Worsened by the PR (pre-existing, but this PR creates additional violations)
   - Pre-existing and unrelated (the repo already had this finding before this PR)
3. **Fix findings introduced or worsened by the PR** — these must be addressed as part of the PR.
4. **Leave pre-existing, unrelated findings untouched** — do not use a PR to clean up the repository's baseline unless the PR explicitly includes work to address them.
5. **Run appropriate targeted validation** — after making fixes, run relevant targeted checks for the changed code. For guidance on validation scope, see `.claude/rules/testing.md`. The normal CI/MegaLinter checks remain the authoritative full validation.
6. **Check whether the branch needs updating** — see `.claude/rules/branch-currency.md`. Update the branch only when being behind `main` actually matters.
7. **Commit and push the fixes** — commit and push the completed, validated changes, following the commit and push policy in `CLAUDE.md`.
8. **Do not modify `.mega-linter.yml` to suppress PR findings** — do not weaken checks, add exclusions, or disable linters to make this PR's own findings go away. A configuration change the task explicitly asks for is legitimate and is not covered by this rule.

## Do not game MegaLinter

Do not manipulate the validation configuration to hide genuine PR-related problems. Forbidden approaches include:

- Disabling a linter because it reports a PR finding
- Adding unnecessary exclusions or suppressions to suppress PR violations
- Weakening MegaLinter configuration (changing rules, thresholds, or severity levels)
- Removing legitimate code solely to avoid a lint finding
- Weakening or removing tests to improve coverage or reduce findings
- Altering coverage thresholds to pass codecov checks
- Using other CI bypass techniques

The existing `.mega-linter.yml` baseline and its handling of pre-existing findings must be preserved, unless the task explicitly asks for a configuration change.

## Example workflow

A PR introduces a new linting finding and also worsens an existing linting finding:

1. The new finding is **introduced by the PR** — fix the underlying issue in the new code.
2. The existing finding is **worsened by the PR** — fix the issue in the code changed by this PR.
3. If the repository has pre-existing linting findings elsewhere (unrelated to the PR), leave them alone — they are not this PR's responsibility.
4. Run appropriate targeted validation for the changed files.
5. Push the fixes.

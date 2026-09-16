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
5. **Run appropriate targeted validation** — after making fixes, run the relevant MegaLinter checks or the full CI suite as needed. For guidance on validation scope, see `testing.md`.
6. **Do not modify `.mega-linter.yml`** — do not weaken checks, add exclusions, or disable linters to suppress PR findings.

## Do not game MegaLinter

Do not manipulate the validation configuration to hide genuine PR-related problems. Forbidden approaches include:

- Disabling a linter because it reports a PR finding
- Adding unnecessary exclusions or suppressions to suppress PR violations
- Weakening MegaLinter configuration (changing rules, thresholds, or severity levels)
- Removing legitimate code solely to avoid a lint finding
- Weakening or removing tests to improve coverage or reduce findings
- Altering coverage thresholds to pass codecov checks
- Using other CI bypass techniques

The existing `.mega-linter.yml` baseline and its handling of pre-existing findings must be preserved.

## Example workflow

A PR adds code that triggers a new bandit security warning and also worsens an existing mypy type hint:

1. The bandit finding is **introduced by the PR** — fix the security issue or add a proper type hint.
2. The mypy finding is **worsened by the PR** — fix the type hint in the new code.
3. If the repository has pre-existing mypy warnings elsewhere, leave them alone — they are not this PR's responsibility.
4. Run targeted validation: `mypy` on the changed files, or the full MegaLinter check.
5. Push the fixes.

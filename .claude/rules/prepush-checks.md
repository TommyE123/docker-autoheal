# Pre-push checks

Checks to run around a push, so CI doesn't find what you could have found locally. They are targeted: follow `.claude/rules/testing.md` and don't reproduce the whole CI pipeline locally. CI remains authoritative.

## 1. Sync first

Run `git fetch origin <branch>` before the first push of a session and after any pause, when the branch already exists on the remote. A brand-new branch has nothing to fetch (the fetch fails with "couldn't find remote ref"), so go straight to the push. If the remote branch has commits you don't have, merge them with `git merge origin/<branch>` (merge, not rebase, as in `.claude/rules/branch-currency.md`). This is separate from merging `origin/main`, which only happens when `branch-currency.md` says it matters.

## 2. Lint the file types you changed

`.linter-rules/.mega-linter.yml` lists which linters run, and most configs are in `.linter-rules/`. Run the linters for each file type you changed, not just one. Skip this for comment-only and prose-only edits, as `.claude/rules/testing.md` allows. For example, Markdown has more than one linter, and a table can pass markdownlint and still fail the table formatter. Also check what the repo's static analysis flags in the code you touched, such as Semgrep rules on logging calls. For Python, run pyright as well as ruff, and run ruff with `--config .linter-rules/.ruff.toml` on the files you changed only, because the config isn't in the root, so the default settings reformat unrelated code, and repo-wide runs report or fix findings the PR didn't introduce.

## 3. Python version and coverage

Use the Python version the `Dockerfile` targets, not whatever is installed (for example with `uv run --python <version>` if `uv` is available). When you add or change Python code, run coverage on the touched modules before pushing and test the new branches, including failure and startup paths. When behaviour changes, check that the existing tests still reach the paths they were written for, since a test can keep passing and no longer exercise its error path.

## 4. SonarCloud, after each push

SonarCloud only analyses the pushed head, so check it after each push once a PR exists (the first push comes before the PR is opened, so check right after opening it) instead of waiting for CI to fail. Wait until the SonarCloud check on the pushed head has completed (`gh pr checks <N>`). The issues query returns `"total":0` with HTTP 200 for an unanalysed head, a wrong PR number or a wrong key, so an empty result means nothing until you confirm the analysed commit is the pushed head:

```bash
curl -sS "https://sonarcloud.io/api/project_pull_requests/list?project=TommyE123_docker-autoheal"
curl -sS "https://sonarcloud.io/api/issues/search?componentKeys=TommyE123_docker-autoheal&pullRequest=<N>&resolved=false"
```

The first call shows the commit SHA analysed for each PR. Only trust the second once it matches the pushed head. If SonarCloud reports new issues, fetch their details with the second call straight away. Never report a count you haven't read. Fix issues the PR introduced. Leave pre-existing ones alone.

## 5. Docs, searched by concept

When behaviour changes, search `docs/` and the README for the concept (for example "authentication"), not only the phrases you expect. Update any statement the change makes false.

## 6. PR descriptions

State only what is true when you write it, and update the description when the work changes, including figures such as the number of tests. Don't describe a check you have replaced, and don't promise to report results later.

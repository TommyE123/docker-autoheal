# Mutation testing

Coverage tells you which lines the tests execute. Mutation testing tells you whether the
tests would notice if those lines changed: [Mutmut](https://mutmut.readthedocs.io/) makes
small changes to the production code (a "mutant", e.g. `>=` becomes `>`), runs the unit
tests against each one, and reports whether any test failed (the mutant was **killed**) or
all of them still passed (the mutant **survived**).

It is informational only. It is not part of `pytest`, is not a required check or merge
gate, and has no score threshold. It is complementary to the coverage reported to Codecov
and is deliberately kept out of it.

## Running it locally

Mutmut needs `fork`, so run it on Linux or macOS (on Windows, use WSL). Use the same
Python version as the `Dockerfile`.

```bash
pip install -r requirements-dev.txt        # already done in the Dev Container

./mutation.sh                              # full run: a few minutes on 4 vCPUs
./mutation.sh "app.uptime_kuma.matching*"  # focused run on a subset of mutants
```

In VS Code (including the Dev Container, which installs `requirements-dev.txt`) the
**Autoheal: Run Mutation Testing** task runs the full `./mutation.sh`. CI runs the same
script.

`mutation.sh` deletes `mutants/` and then runs `mutmut run`, so every run starts clean.
It finishes by printing the mutants that were not killed. `mutants/` is git-ignored.

### Why every run starts clean

Mutmut caches verdicts in `mutants/` and does not invalidate them when a test is added or
an existing test is edited: a plain `mutmut run` after changing a test can report the old
survivors. Starting from an empty `mutants/` is the only way to be sure a result reflects
the current tests. If you call `mutmut` directly instead of `mutation.sh`, delete
`mutants/` first (or name the mutants you want re-evaluated, e.g.
`mutmut run "app.uptime_kuma.matching*"`).

A focused run leaves every other mutant as `not checked`, and `mutmut export-cicd-stats`
counts those in its total, so its score is only meaningful after a full run.

## Inspecting results

All of these work with Mutmut alone. Run them from the repository root after a run:

```bash
mutmut results                # survivors, timeouts and mutants with no tests
mutmut results --all true     # every mutant, including killed
mutmut show <mutant-name>     # the diff for one mutant, e.g. app.uptime_kuma.matching.x_normalize_name__mutmut_1
mutmut tests-for-mutant <mutant-name>
mutmut browse                 # interactive browser
mutmut export-cicd-stats      # writes mutants/mutmut-cicd-stats.json
```

A mutant name is `<module>.<function>__mutmut_<n>`. The number is positional, so it
changes when the surrounding code changes: compare survivors between runs by file,
function and the changed text, not by name.

## CI run

`.github/workflows/mutation-testing.yml` runs the same `./mutation.sh`, always the full
suite. It runs:

- automatically on pull requests to `main`, and on pushes to `main`, that change
  `app/**/*.py` (production code or tests), `requirements*.txt`, `pyproject.toml`,
  `mutation.sh`, the `Dockerfile` (which sets the Python version) or the workflow itself;
  documentation-only and other unrelated changes do not run it;
- manually, from the Actions tab (**Mutation Testing** -> **Run
  workflow**).

A run takes about 4-5 minutes on a GitHub-hosted runner (235-327 s per job over eight
successful runs, of which 214-279 s is the mutation step).

The workflow:

- installs `requirements-dev.txt` on the Python version the `Dockerfile` uses;
- starts from an empty `mutants/` (and never caches it);
- is grouped by ref: a new push to a pull request cancels that PR's in-progress run, while runs on `main` and manual runs are never cancelled once running (a newer run can still replace one that is only queued);
- is informational: it is not a required check, has no score threshold, and must not be
  made one.

The README badge shows the mutation score stored in `.github/badges/mutation.json`, a
small Shields endpoint file on `main`. `mutmut badge` generates it from the exported
stats; nothing calculates the score by hand. The score equals the **Detected** figure in
the job summary, since no mutants are skipped. It is informational only: the run succeeds
whatever the score, so no threshold is implied, and it is not a gate.

The file is updated by the pull request that changes the score:

- A full `./mutation.sh` run (no arguments) rewrites the file locally.
  Focused runs leave it alone, because they score only part of the target.
- On a pull request from this repository, the workflow's `commit-badge` job commits the
  new file to the PR branch as `ci: update mutation badge`, unless it is unchanged. Only
  that job has a write token. Fork pull requests get no write token, so they never
  commit: they add a notice and a line to the job summary if the file differs. The new
  file is in the `mutation-badge` artifact. Runs on `main` never commit.
- The commit is pushed with the `BADGE_PUSH_TOKEN` repository secret, a fine-grained
  personal access token with **Contents: read and write** on this repository. A push made
  with `GITHUB_TOKEN` would not start the PR's other checks, leaving the required ones
  missing on the new head. The badge commit does start them, but the workflow's `gate` job
  skips the mutation run for it, since the commit only changes the badge file. If the token
  expires or is removed, or branch protection rejects the push, the `commit-badge` job
  fails (the mutation job itself stays green) and the badge keeps its last score.
- If the file is left stale, the badge simply keeps showing the last committed score.

Find results on the workflow run page (for a pull request, the **Mutmut**
check's details link):

- the **job summary** shows the counts and the score;
- the **`mutation-results`** artifact contains `mutation-results.txt` (survivors, timeouts
  and no-test mutants), `mutmut-cicd-stats.json`, and the `mutants/` tree with Mutmut's
  per-file `.meta` verdicts.

To browse a CI run with `mutmut show` or `mutmut browse`, download the artifact into
`mutants/` at the repository root (e.g. `gh run download <run-id> -n mutation-results -D mutants`)
and use the commands above.

## Targeted run: API server smoke test ([#412](https://github.com/TommyE123/docker-autoheal/issues/412))

`app/tests/unit/test_main_api_server_smoke.py` is part of the normal unit suite and the
mutation run (Mutmut ignores only the repository-file tests `test_release_please_workflow.py`
and `test_dev_stack_files.py`). It runs the real
`app.main.run_api_server()` against a real Uvicorn server. The code it exercises is mutated as
follows (focused runs; the verdicts are valid because `mutation.sh` starts from an empty
`mutants/`):

```bash
./mutation.sh "app.main.x_run_api_server*"   # 18 mutants: all killed
./mutation.sh "app.api*"                     # all mutants killed, none survive
```

- `run_api_server`: every mutant is killed (by the smoke test and the mocked
  `test_main_lifecycle.py::TestRunApiServer`).
- The smoke test requests only `/health` and `/api/status`. Those handlers are decorated, so
  Mutmut does not mutate them (see [Known limitations](#known-limitations)).
- `app/api/routes/ui.py` initially had 33 survivors (static-file serving and the fallback
  page). They were killed by tests added to `test_static_file_serving.py`: exact fallback
  page and error details, `utf-8` encoding, media-type defaults, subdirectory and directory
  path handling, and the success and error log messages. No equivalent mutants remain
  undocumented: `"utf-8"` vs `"UTF-8"` is behaviourally equivalent but the test pins the
  exact spelling.

## Reading the score

The score is `(killed + timeout) / generated`. A timeout counts as detected: a mutant that
makes the code hang was noticed. It is only comparable between runs with the same
configuration, scope and Mutmut version. Read the list of survivors first, and treat the
percentage as a trend. Survivors on statements the suite executes are the useful ones; many
of the rest are noise (log messages, string literals, cosmetic constants).

## Configuration

`pyproject.toml` contains only a `[tool.mutmut]` table; `pytest.ini` and `.coveragerc`
still own test and coverage settings. Every non-default setting has a reason from the
Phase 1 evaluation in [#333](https://github.com/TommyE123/docker-autoheal/issues/333):

| Setting                              | Why                                                                                                                                                                                                            |
|--------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `source_paths = ["app"]`             | Required: Mutmut's automatic detection fails for this repository's directory name.                                                                                                                             |
| `do_not_mutate`                      | Without `app/tests/*` Mutmut mutates the tests themselves (about 13.6k extra mutants, including the integration suite). `.coveragerc` omits it too.                                                            |
| `pytest_add_cli_args_test_selection` | `test_release_please_workflow.py` and `test_dev_stack_files.py` read `.github/`, `.vscode/` and Compose files that do not exist inside `mutants/` and abort stats collection. They import nothing from `app/`. |

Deliberately left at Mutmut's defaults:

- `mutate_only_covered_lines`: Phase 1 measured no runtime benefit, and leaving it off
  keeps mutants in code the tests never run visible as `no tests`.
- `process_isolation` (fork): `forkserver` gave identical verdicts but was about 47%
  slower.
- `max_stack_depth`: it crashes stats collection in this repository.
- No `# pragma: no mutate` and no other exclusions: survivors, including noisy ones such
  as log calls, stay visible.

Integration tests are not part of the mutation run. Their fixtures skip when a
prerequisite is missing, and a skipped test cannot kill a mutant.

## Known limitations

- **Decorated functions are not mutated.** Mutmut skips any function with a decorator other
  than a lone `@staticmethod`/`@classmethod`. That is 50 of 182 production functions in
  the Phase 1 measurement, including every FastAPI route handler, so the score says nothing
  about the HTTP API layer. This is a documented limitation, not something the workflow
  works around; see #333 for the follow-up discussion.
- Mutmut has no operator that removes an `await`; missing awaits are a linter/type-checker
  concern.
- Stale state: see [Why every run starts clean](#why-every-run-starts-clean).

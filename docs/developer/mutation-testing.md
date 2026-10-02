# Mutation testing

Coverage tells you which lines the tests execute. Mutation testing tells you whether the
tests would notice if those lines changed: [Mutmut](https://mutmut.readthedocs.io/) makes
small changes to the production code (a "mutant", e.g. `>=` becomes `>`), runs the unit
tests against each one, and reports whether any test failed (the mutant was **killed**) or
all of them still passed (the mutant **survived**).

It is informational only. It is not part of `pytest`, is not a pull-request check, and has
no score threshold. It is complementary to the coverage reported to Codecov and is
deliberately kept out of it.

## Running it locally

Mutmut needs `fork`, so run it on Linux or macOS (on Windows, use WSL). Use the same
Python version as the `Dockerfile`.

```bash
pip install -r requirements-mutation.txt   # already done in the Dev Container

./mutation.sh                              # full run: a few minutes on 4 vCPUs
./mutation.sh "app.uptime_kuma.matching*"  # focused run on a subset of mutants
```

In VS Code (including the Dev Container, which installs `requirements-mutation.txt`) the
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

## Weekly CI run

`.github/workflows/mutation-testing.yml` runs the same `./mutation.sh`. It has no GitHub
`schedule` trigger because GitHub's scheduler is unreliable; it is `workflow_dispatch`
only, and is meant to be started every Monday by [cron-job.org](https://cron-job.org/)
calling the GitHub API (`POST /repos/TommyE123/docker-autoheal/actions/workflows/mutation-testing.yml/dispatches`
with body `{"ref": "main"}` and a token that has Actions write access). The schedule and
token live in the cron-job.org account, not in this repository, and nothing here creates
that job: until it is set up, the workflow only runs when started manually from the
Actions tab (**Mutation Testing** -> **Run workflow**). The workflow:

- installs `requirements-mutation.txt` on the Python version the `Dockerfile` uses;
- starts from an empty `mutants/` (and never caches it);
- never cancels a run in progress, and only one mutation run executes at a time;
- is not a pull-request check and cannot block a merge.

Find results on the workflow run page:

- the **job summary** shows the counts and the score;
- the **`mutation-results`** artifact contains `mutation-results.txt` (survivors, timeouts
  and no-test mutants), `mutmut-cicd-stats.json`, and the `mutants/` tree with Mutmut's
  per-file `.meta` verdicts.

To browse a CI run with `mutmut show` or `mutmut browse`, download the artifact into
`mutants/` at the repository root (e.g. `gh run download <run-id> -n mutation-results -D mutants`)
and use the commands above.

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

| Setting                              | Why                                                                                                                                                       |
|--------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `source_paths = ["app"]`             | Required: Mutmut's automatic detection fails for this repository's directory name.                                                                        |
| `do_not_mutate`                      | Without `app/tests/*` Mutmut mutates the tests themselves (about 13.6k extra mutants, including the integration suite). `.coveragerc` omits it too.       |
| `pytest_add_cli_args_test_selection` | `test_release_please_workflow.py` reads `.github/` files that do not exist inside `mutants/` and aborts stats collection. It imports nothing from `app/`. |

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

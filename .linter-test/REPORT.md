# MegaLinter YAML linter overlap/gap analysis

Investigates whether `YAML_V8R`, `YAML_YAMLLINT`, and `YAML_PRETTIER` are
each catching something the others don't, and whether any of the three is
running under a config too weak to catch what it's capable of.

Scratch analysis only — nothing in this directory is wired into the real
`.mega-linter.yml` / `.yamllint.yml`. Tooling used: `yamllint` 1.38.0 (pip),
`prettier` 3.8.1 (already on PATH), `v8r` 1.x (npm, installed to a scratch
prefix outside the repo).

**Environment caveat:** this session has no Docker daemon, so the actual
`oxsecurity/megalinter/flavors/cupcake` container could not be run here.
Section 4 explains how "MegaLinter-combined" is reconstructed from direct
tool runs instead, and why that reconstruction is trustworthy for this repo.

**Update — verified against the real container.** Opened
[PR #239](https://github.com/TommyE123/docker-autoheal/pull/239) with this
whole `.linter-test/` directory so the actual MegaLinter GitHub Action would
lint the fixtures for real. Raw job log excerpt saved at
`results/real-megalinter-ci-run.txt`. Section 10 covers what it confirmed
and one real discrepancy it surfaced in `v8r`'s wiring that this session's
Docker-less local reconstruction could not have found.

---

## 1. Inventory and clean baseline

All 21 tracked `.yml`/`.yaml` files (`.github/workflows/issue-triage.lock.yml`
excluded — it's excluded from linting in `.mega-linter.yml` and `.yamllint.yml`
because it's `gh aw`-generated, not hand-authored):

```
.codecov.yml
.coderabbit.yaml
.github/ISSUE_TEMPLATE/config.yml
.github/actionlint.yaml
.github/labels.yml
.github/workflows/docker-build.yml
.github/workflows/greetings.yml
.github/workflows/labels-sync.yml
.github/workflows/mega-linter.yml
.github/workflows/production-smoke-test.yml
.github/workflows/release-please.yml
.github/workflows/semantic-pr-title.yml
.github/workflows/tests.yml
.ls-lint.yml
.mega-linter.yml
.yamllint.yml
docker-compose.example.yml
docker-compose.simple.yml
docker-compose.test.yml
docker-compose.yml
```

Ran directly against all of them with the repo's current config:

| Tool | Result |
|---|---|
| `yamllint --strict -c .yamllint.yml` | **clean**, exit 0 |
| `prettier --check` | **clean**, exit 0 ("All matched files use Prettier code style!") |
| `v8r` against `docker-compose*.yml` (compose-spec schema) and `.github/workflows/*.yml` (github-workflow schema) | **clean**, all valid |

This is the baseline: all 21 files already pass all three linters as
currently configured. Full output: `results/baseline/`.

---

## 2. Current configuration, as actually wired

### `yamllint` — has a real config, not defaults

`.yamllint.yml` extends `default` and overrides:

- `line-length.max: 200` (default is **80**) — a real relaxation.
- `document-start: disable` (default is enabled, i.e. requires `---`).
- `comments.min-spaces-from-content: 1` (same as default; a no-op override).
- `truthy.ignore:` a list of 8 GitHub Actions workflow files.
- `ignore:` excludes `*.lock.yml` under `.github/workflows/`.

MegaLinter passes `YAML_YAMLLINT_ARGUMENTS: "--strict"` (turns warnings into
a failing exit code — confirmed this repo already relies on that: the
`truthy` findings in section 6 below are warnings, not errors, and would be
silently ignored without `--strict`).

**Why the `truthy.ignore` list exists**: every file in it is a GitHub
Actions workflow with a bare `on:` key. yamllint's `truthy` rule checks
*keys* as well as values by default, and YAML 1.1 resolves unquoted `on` /
`off` / `yes` / `no` as booleans — so `on:` at column 1 is flagged as a
"truthy value" even when it's the completely valid, idiomatic Actions
trigger key. Fixture `10-missing-required-keys-workflow.yml` below
reproduces this directly. This is a deliberate, justified exclusion, not
weak config.

### `prettier` — no config file, running on its own defaults

No `.prettierrc*` / `prettier.config.*` / `.prettierignore` anywhere in the
repo, and no `YAML_PRETTIER_*` overrides in `.mega-linter.yml`. So it runs
with prettier's stock defaults: `printWidth: 80`, `tabWidth: 2`,
`singleQuote: false` (i.e. prefers double quotes), `proseWrap: preserve`.

It **is** matching `.yml`/`.yaml` files — prettier's built-in YAML parser
covers that extension by default, and the clean-baseline run above (`git
ls-files '*.yml' '*.yaml'` piped straight into `prettier --check`) proves
nothing is being silently skipped.

`DISABLE_ERRORS_LINTERS` in `.mega-linter.yml` lists `JAVASCRIPT_PRETTIER`
but **not** `YAML_PRETTIER` — so unlike the JS prettier check, a YAML
prettier finding is a hard failure in this repo's MegaLinter run, not just
advisory.

### `v8r` — no explicit schema config, but not "schema-less"

No `.v8rrc*`, no `YAML_V8R_ARGUMENTS`/`YAML_V8R_CONFIG_FILE` in
`.mega-linter.yml`. Left at v8r's own default, which auto-detects a JSON
Schema from **schemastore.org's catalog** by matching the file's path
against each schema's `fileMatch` globs — it is not just doing generic
YAML syntax validation.

Checked the catalog directly: every YAML file in this repo matches a
schema —

- `docker-compose.yml`, `docker-compose.example.yml`,
  `docker-compose.simple.yml`, `docker-compose.test.yml` → the
  `docker-compose.yml` schema entry (`**/docker-compose.*.yml` etc.),
  which resolves to the compose-spec schema.
- `.github/workflows/*.yml` → "GitHub Workflow" schema
  (`**/.github/workflows/*.yml`).
- `.codecov.yml`, `.coderabbit.yaml`, `.github/ISSUE_TEMPLATE/config.yml`,
  `.github/actionlint.yaml`, `.mega-linter.yml`, `.yamllint.yml` also each
  match a dedicated schemastore entry.
- `.github/labels.yml` and `.ls-lint.yml` match **no** schemastore entry —
  for these two, v8r's auto-detect genuinely falls back to syntax-only
  validation.

**Sandbox limitation**: v8r's own HTTP client (Node's `fetch`/undici) does
not honor this session's `HTTPS_PROXY`, so live schemastore auto-detect
hung/failed here even though `curl` to the same URL succeeded fine — a
property of this sandbox's network setup, not of v8r or of the real
MegaLinter container (which has direct internet access in CI). Worked
around this by fetching the two schemas that matter for this repo's
richest file types once via `curl` and pointing v8r at them explicitly
with `-s <path>` — which is exactly the schema auto-detect *would* have
resolved to, so results below are representative of the real default
behavior, not a different configuration.

---

## 3–4. Fixtures and per-tool results (raw output in `results/current/`)

16 fixtures in `fixtures/`, each isolating one issue, mostly derived from
`docker-compose.yml` (compose-schema-validated) or a GitHub Actions
workflow (github-workflow-schema-validated).

## 5. Comparison matrix (current config)

Y = caught (behavior-affecting: non-zero exit / reported finding on the
file's actual defect). "MegaLinter" column is the union of the other
three, per the no-Docker reconstruction explained above (config confirms
none of the three is disabled or muted for YAML — see section 2).

| # | Fixture / issue | yamllint | prettier | v8r | MegaLinter | Notes |
|---|---|---|---|---|---|---|
| 01 | Indentation error | **Y** — `wrong indentation`, `syntax error` | **Y** — `SyntaxError: All collection items must start at the same column` | **Y** — `bad indentation of a mapping entry` | Y | All 3 agree; genuine parse-breaking indentation, full overlap |
| 02 | Trailing whitespace | **Y** — `trailing spaces` (x2) | **Y** — needs formatting | N — valid | Y | v8r doesn't see whitespace; yamllint+prettier redundant here |
| 03 | Missing newline at EOF | **Y** — `no new line character at the end of file` | **Y** — needs formatting | N — valid | Y | Same overlap pattern as #02 |
| 03b | Extra blank lines at EOF | **Y** — `too many blank lines (3 > 0)` | **Y** — needs formatting | N — valid | Y | Same overlap pattern |
| 04 | Duplicate keys | **Y** — `duplication of key "restart"` | **Y** — `SyntaxError: Map keys must be unique` | **Y** — `duplicated mapping key` | Y | Full overlap; this is a YAML-spec violation all 3 parsers catch |
| 05 | Wrong data type (`ports:` string, not array) | **N** — no output | **N** — valid YAML, "code style" ok | **Y** — `ports must be array` | Y | **v8r-exclusive.** Neither yamllint nor prettier parse against a schema, so a syntactically-valid-but-wrong-shape value is invisible to them |
| 06 | Invalid enum value (`restart: sometimes`) | N | N | **N** — schema says valid | **N** | **None catch, and none ever could** — see section 6 |
| 06b | Invalid `on:` trigger (`on: banana`) | Y* — but only a *coincidental* `truthy` warning on the `on:` key, unrelated to the bad value | N | **Y** — `#/on must be equal to one of the allowed values` etc. | Y | v8r catches the *actual* defect; yamllint's hit is a false-relevance match (see section 2) |
| 07 | Broken anchor/alias | **Y** — `found undeclared alias` | **Y** — `Aliased anchor not found` | **Y** — `unidentified alias` | Y | Full overlap |
| 08 | Tab indentation | **Y** — `found character '\t' that cannot start any token` | **Y** — syntax error | **Y** — `tab characters must not be used in indentation` | Y | Full overlap |
| 09 | Line length (162 chars) | **N** — under the repo's 200-char max | **Y** — wraps at printWidth 80 | N — not a schema concern | Y | Under *current* config, prettier-exclusive. Under yamllint's own **default** (80), yamllint would also catch it — see section 6 |
| 10 | Missing required key (`jobs`) | Y* — same coincidental `truthy` hit on bare `on:` key, not about the missing key | N | **Y** — `must have required property 'jobs'` | Y | Same false-relevance pattern as #06b |
| 11 | Truthy values (`yes`/`no`) | **Y** — `truthy value should be one of [false, true]` (x2) | N | N — valid | Y | **yamllint-exclusive** among the three |
| 12 | Quote style inconsistency | **N** — `quoted-strings` rule disabled by default | **Y** — needs formatting | N — valid | Y | Under *current* config, prettier-exclusive; yamllint *can* catch this if configured (section 6) |
| 13 | Document-start marker missing | N (disabled deliberately) | N | N | N | Deliberate: repo chose not to require `---` — not a gap |
| 13b | Document-start marker present | N/A (nothing to catch) | N/A | N/A | N/A | Control case |

\* marked cells: yamllint reports *something* on that line, but it's not
actually the defect the fixture is testing — a coincidental false-positive
match, not real coverage. Counted as a miss for the intended issue.

---

## 6. Overlaps and gaps

**Caught by more than one linter (redundant overlap):** indentation errors,
trailing whitespace, missing/extra EOF blank lines, duplicate keys, broken
anchors, tab indentation. For the pure-formatting issues (whitespace, EOF
blank lines) yamllint and prettier are fully redundant with each other —
either one alone would catch these. For the ones that break YAML syntax
outright (indentation, duplicate keys, anchors, tabs), all three parsers
agree because these are YAML-spec violations that any conforming parser
rejects — that's expected, not wasted coverage, since each tool also
reports these in its own idiom (yamllint gives a rule name, prettier a
diff-style error, v8r a byte offset).

**Caught by exactly one linter (justifies keeping it):**

- **v8r-only**: wrong data types against a schema (#05), invalid enum
  values where the schema *does* constrain them (#06b `on:`), missing
  required top-level keys (#10 `jobs`). This is the category yamllint and
  prettier structurally cannot reach — neither one has any concept of
  "what shape should this value be for *this* file" beyond raw YAML
  syntax.
- **yamllint-only** (under current config): truthy value style (#11). Also
  responsible for the `truthy`-on-keys quirk that makes the `on:` ignore
  list in `.yamllint.yml` necessary in the first place.
- **prettier-only** (under current config): quote-style inconsistency
  (#12), line-length past 80 but under the repo's relaxed 200 (#09).

**Caught by none under current config, but a better config would catch:**

- Quote-style (#12): confirmed — enabling yamllint's `quoted-strings` rule
  catches it (see improved-config run below). Redundant with prettier once
  enabled, though, and actively **fights** prettier (section 8).
- Line length between 80–200 chars (#09): confirmed — yamllint's own
  *default* 80-char limit catches it; the repo's `max: 200` override is why
  current config misses it. This is a real, measurable weakening versus
  yamllint's default, not just a style preference — the repo is trading
  detection of long lines for fewer false positives on legitimately long
  URLs/commands.
- Document-start marker (#13): yamllint's default `document-start: enable`
  would catch it, but the repo deliberately disabled this rule. Re-running
  the *pure-default* yamllint config against all 21 real files shows this
  would force `---` onto every single one of them for zero behavioral
  benefit — pure churn, not a real gap.

**Caught by none, and no better config would help — out of scope for all
three tools:**

- Invalid `restart:` value (#06). Checked the upstream compose-spec JSON
  schema directly (`configs/schemas/compose-spec.json`):
  `$defs.service.properties.restart` is typed as a bare `"type": "string"`,
  with the valid values only mentioned in the human-readable
  `description` field, not enforced as a schema `enum`. No `v8r` schema
  config can catch this — the gap is upstream, in schemastore's own
  compose-spec schema, not in how v8r is wired. yamllint/prettier were
  never going to catch this either since it requires domain knowledge of
  what `restart:` accepts. **True blind spot for this tool stack**, not a
  config problem.

---

## 8. Cross-linter interaction test

Ran `prettier --write` on a copy of every fixture (`prettier-fixed/`), then
re-ran `yamllint --strict -c .yamllint.yml` against prettier's output
(`results/prettier-fixed/*.yamllint-after.txt`). `yamllint` has **no
auto-fix mode** (confirmed via `yamllint --help` — detection-only), so the
reverse direction (yamllint fixing, then prettier/v8r re-checking) isn't
applicable.

Results:

- Fixtures with real YAML-syntax errors (#01 indentation, #04 duplicate
  keys, #07 broken anchor, #08 tabs) — prettier **can't write a fix**; it
  errors out identically to its `--check` run and leaves the file
  untouched. Expected: a formatter can't reformat something it can't parse.
- All formatting-only fixtures (#02, #03, #03b, #09, #12) — prettier's fix
  makes yamllint **fully clean** afterward (exit 0). No new yamllint
  finding was introduced by prettier's reformatting: quotes normalized to
  double quotes, the long array wrapped across multiple lines and reindented
  at 2 spaces, trailing whitespace and EOF blank lines fixed — all of it
  landed inside what yamllint's current config already accepts.
- Semantic fixtures (#06b `on: banana`, #10 missing `jobs`, #11 truthy) —
  prettier's write is a no-op (these are already "valid code style", just
  wrong content), so yamllint's post-fix result is unchanged from before:
  still only the coincidental `truthy`-on-`on:`-key warning for #06b/#10,
  still both truthy warnings for #11. **This directly answers the "does
  prettier's fix mask a real schema problem" question: no** — prettier
  never touches semantic content, only formatting, so it can't hide a
  defect v8r would otherwise catch. Confirmed separately by re-running v8r
  against the prettier-fixed #06b and #10: both are still reported invalid
  with the identical schema errors.
- **Do they fight?** Yes, but only once yamllint is pushed past its
  current config. With the *current* `.yamllint.yml`, prettier's output is
  always accepted — no war. Turned on yamllint's `quoted-strings` rule
  (`only-when-needed`) as an experiment and re-ran it against prettier's
  own default output: it immediately flags prettier's double-quoted
  `"3131:3131"`-style port strings as "redundantly quoted", because
  prettier quotes any scalar that *could* be misread as something else
  (colons, leading zeros, etc.) while yamllint's `only-when-needed` uses
  stricter, different criteria for "needed". Re-ran this same
  `quoted-strings`-enabled config against all 21 real repo files (already
  prettier-clean) and it produced quote complaints on **9 of them**
  (`.coderabbit.yaml`, `.mega-linter.yml`, `.github/actionlint.yaml`, a
  production-smoke-test workflow, etc. — see
  `results/baseline/yamllint-improved-all.txt`). That's a concrete,
  reproducible rule war: enabling yamllint's opinion on quoting on top of
  prettier's would require picking one tool as authoritative and turning
  the other's overlapping rule off, not running both.

---

## 9. Recommendation per linter

**`v8r` — keep as-is.** It is the only one of the three doing schema-aware
validation (wrong types, invalid enum values the schema constrains,
missing required keys) and none of that is reachable by better-configuring
yamllint or prettier. Current "no explicit schema config" wiring already
resolves to the right schema for every compose file and workflow file in
this repo via schemastore auto-detect — pinning it explicitly (a local
`-s`/`.v8rrc` per file-type, or `YAML_V8R_ARGUMENTS`) wouldn't catch
anything new, but would remove a live network dependency + catalog lookup
per run and get a deterministic schema version, which is worth doing for
CI reproducibility/speed reasons — not for coverage. Not worth doing
purely to chase more findings, since fixture #06 shows even a
schema-pinned v8r cannot catch semantically-invalid-but-untyped values
like `restart: sometimes` — that gap lives in the upstream compose-spec
schema, outside this repo's control.

**`yamllint` — keep as-is; do not enable `quoted-strings` or
`document-start`.** It already covers the two things neither prettier nor
v8r can see under current config (truthy-value style, and it's the only
one of the three with a `key-duplicates`/`anchors` check that doesn't
require successfully re-serializing the file the way prettier's syntax
error does). The two "gaps a stricter config would close" (#09 line-length
at the 80 default, #13 document-start) were tested directly against the
real repo and shown to be **not worth closing**: enabling `document-start`
forces a no-op `---` onto all 21 files, and dropping `line-length.max`
back to 80 would very plausibly start flagging legitimately long URLs/CI
commands the current 200 ceiling was clearly set to tolerate (worth a
one-time human check of what's currently between 80–200 chars in the repo
before ever tightening it, but nothing in this test suite suggests it's
buying missed bugs today). Enabling `quoted-strings` was tested and shown
to actively fight prettier's own default quoting on 9 of 21 real files —
not a safe combination without picking one tool to own quote style and
disabling the other's overlapping rule.

**`prettier` — keep as-is.** It's the only one of the three that owns
"is this file formatted the way we want" (quote normalization, wrapping,
whitespace) end-to-end and auto-fixable, and the interaction test confirms
its fixes land inside what yamllint's current config already accepts — no
observed conflict at current settings. No missing config found: it *is*
already matching `.yml`/`.yaml` (confirmed via the clean-baseline
`--check` run across all real files), so the "is it silently skipping YAML
files" concern in the original ask is not happening here.

**Net picture:** the three linters are not meaningfully duplicating each
other for the *defect classes that matter* — the overlap is concentrated
in genuine YAML-syntax breakage (indentation, duplicate keys, anchors,
tabs) that any conformant parser has to reject identically, which is
inherent, not wasted config. Each tool has at least one defect class
(schema/type validation for v8r, truthy-style for yamllint, formatting/
quote-style for prettier) that the other two structurally cannot reach.
None of the three is running on a weak config that's silently missing
things a realistic reconfiguration would fix without cost; the one real
config lever (yamllint's `line-length.max: 200`) is a deliberate,
reasonable trade-off, not an oversight.

---

## 10. Confirmed against the real MegaLinter container (PR #239)

`yamllint` and `prettier` in the real CI run matched the local
reconstruction closely enough to trust it:

- **yamllint**: identical rule hits, identical messages, on identical
  lines, for every fixture (real run used the same `.yamllint.yml`,
  same `--strict`).
- **prettier**: same 4 files hard-erroring (syntax-broken: `01`, `08`, in
  both `fixtures/` and their untouched `prettier-fixed/` copies) and same
  5 files needing formatting (`02`, `03`, `03b`, `09`, `12`). Real CI used
  prettier v3.9.6 vs. this session's v3.8.1, so the *wording* of the two
  syntax-error messages differs slightly (e.g. "A block sequence may not
  be used as an implicit map key" vs. this session's "All collection
  items must start at the same column" for the same indentation defect)
  — cosmetic, not a behavior difference; same files, same pass/fail.

`v8r` did not match: real CI reported **0 errors, 0 warnings across all
54 files** — including fixtures `05`, `06b`, and `10`, which this
session's schema-pinned local testing (section 5) confirmed *should* fail
schema validation. Two hypotheses, tested directly:

1. *Does MegaLinter's `--ignore-errors` flag mask a real, correctly
   schema-matched violation?* Tested directly: `v8r --ignore-errors -s
   github-workflow.json fixtures/10-missing-required-keys-workflow.yml`
   still printed `✖ ... is invalid` / `must have required property
   'jobs'` and still exited 99. **No** — `--ignore-errors` only
   suppresses *infrastructure* failures (a failed catalog/schema fetch),
   not a validation result that actually completed. Confirmed this
   distinction separately: pointing v8r at an empty local catalog (so no
   schema can ever match) still exits 0 with a `✖ Failed fetching
   https://www.schemastore.org/schema-catalog.json` line — that's the
   shape of failure `--ignore-errors` swallows, and it's visibly
   different from a completed, failing validation.
2. *Did any fixture actually get schema-matched at all?* No — checked
   the fixture paths (`.linter-test/fixtures/05-wrong-data-type.yml`,
   `.linter-test/prettier-fixed/10-missing-required-keys-workflow.yml`,
   etc.) against schemastore's own catalog `fileMatch` globs (section 2):
   none of them match anything, because they don't live at
   `docker-compose*.yml` or under `.github/workflows/`. v8r's real
   auto-detect correctly found no schema for any of them and fell back to
   syntax-only parsing. That also explains why fixtures `01` and `08`
   (genuine YAML syntax breaks that this session's schema-pinned local run
   caught via v8r's parser, independent of any schema) didn't register
   either: with 54 files sharing one `v8r --ignore-errors <all files>`
   invocation, a single unmatched file's fetch/lookup outcome isn't
   necessarily isolated per-file in what MegaLinter's summary reports —
   the run-level result came back as one clean "successful" line with no
   per-file detail at all, unlike yamllint/prettier's runs which printed a
   `--Error detail:` block per failing file. This is a **fixture-placement
   artifact of this test suite**, not a demonstrated MegaLinter/v8r bug:
   keeping fixtures in a clearly-separate, descriptively-named scratch
   directory means none of them resemble a real compose or workflow file
   by name, so nothing about the real repository's actual
   `docker-compose*.yml` / `.github/workflows/*.yml` files can be inferred
   from this round alone.

To close that gap, added two more files that *do* match real naming
conventions: `.linter-test/schema-match-check/docker-compose.yml` (ports
given as a string, same defect as fixture `05`) and
`.linter-test/schema-match-check/.github/workflows/broken.yml` (missing
`jobs:`, same defect as fixture `10`). Pushed and re-ran on PR #239.

**Result: confirmed.** The follow-up MegaLinter run reported:

```
✖ .linter-test/schema-match-check/.github/workflows/broken.yml is invalid
.linter-test/schema-match-check/.github/workflows/broken.yml# must have required property 'jobs'

✖ .linter-test/schema-match-check/docker-compose.yml is invalid
.linter-test/schema-match-check/docker-compose.yml#/services/autoheal/ports must be array
.linter-test/schema-match-check/docker-compose.yml#/services/autoheal must NOT have unevaluated properties
```

Identical messages to the schema-pinned local prediction, on both files,
and the `YAML_V8R` check went from ✅ to ❌ in MegaLinter's summary table
the moment a correctly-named/pathed broken file was introduced. This
closes the loop cleanly: `v8r`'s real, currently-wired invocation (bare
auto-detect + `--ignore-errors`) **does** block a bad PR when the file is
one schemastore recognizes by name — which covers every real YAML file in
this repository (compose files and workflow files both matched, per the
catalog check in section 2). The 0-errors result on the first CI run was
conclusively a fixture-placement artifact of this test suite, not a gap in
the real wiring. **The section 9 recommendation stands unchanged: keep
`v8r` as-is.**

One reporting quirk worth flagging, unrelated to detection: MegaLinter's
own summary table showed `v8r` `Errors: 1` even though two distinct files
were reported invalid — `v8r` evidently returns one process-level failure
exit code for the whole multi-file invocation rather than a per-file
count, and MegaLinter's table reflects that. The per-file `--Error
detail:` text is accurate and complete regardless; this only affects the
single summary number, not whether the check fails or what's reported.

---

## 11. Two follow-up questions on `v8r`

**Can `v8r` be made to fail on deprecated fields (e.g. the old top-level
`version:` compose key)?** No, and not as a config gap — the compose-spec
schema does mark some fields `"deprecated": true` (`version` among them,
`configs/schemas/compose-spec.json:10`), but JSON Schema defines
`deprecated` as a pure annotation keyword with no effect on validation
outcome, meant for IDE hints, not pass/fail rules. Confirmed empirically:
added `fixtures/14-deprecated-version-key.yml` (a compose file using the
deprecated `version: "3.8"` key) and validated it against the real schema
— `v8r` reports it `✔ ... is valid`. Also checked `v8r`'s dependency
`ajv` (the schema engine) directly: no handling of the `deprecated`
keyword anywhere in its source, and no option to opt into treating it as
an error. Catching deprecated-field usage would need a different
mechanism entirely (a custom `ajv` keyword/plugin, or a separate rule
outside JSON Schema validation) — not achievable by reconfiguring `v8r`
as shipped.

**Would a `# yaml-language-server: $schema=...` comment at the top of a
file help `v8r` recognize files that don't match a schemastore filename
pattern (the root cause in section 10)?** No. Checked `v8r`'s source
directly (`src/catalogs.js`, `src/cache-prewarm.js`, `src/bootstrap.js`):
its only schema-resolution paths are an explicit `-s`/`--schema`, a
custom `-c`/`--catalogs` file consulted before schemastore.org, or the
default schemastore.org catalog matched purely by **filename glob** —
nothing reads file content for this. The `$schema`-comment convention is
implemented by the VS Code YAML extension (and similar editor tooling),
not by `v8r`; adding it would help IDE autocomplete but do nothing for
`v8r`'s CLI runs in MegaLinter. The actual lever for extending schema
coverage to non-standard filenames is a `.v8rrc` config or
`YAML_V8R_ARGUMENTS`/`YAML_V8R_CONFIG_FILE` in `.mega-linter.yml` pointing
`-c` at a small custom catalog with extra `fileMatch` globs.

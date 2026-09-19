# Changelog

This file is maintained by [Release Please](https://github.com/googleapis/release-please) as
part of its standing Release PR process. Entries through `v2.0.16` are the project's real,
pre-Release-Please release history (from the repository's existing GitHub Releases), seeded here
so the changelog isn't starting from nothing; entries from this point forward are generated
automatically from Conventional Commit PR titles.

## [2.1.0](https://github.com/TommyE123/docker-autoheal/compare/v2.0.16...v2.1.0) (2026-09-19)


### Features

* add ESLint + Prettier for frontend JS/JSX, retire StandardJS ([#159](https://github.com/TommyE123/docker-autoheal/issues/159)) ([9c844e2](https://github.com/TommyE123/docker-autoheal/commit/9c844e2adcc716d009bb9b5257ff2c834c9205b7))
* add gh-aw powered issue triage and reset label taxonomy ([#154](https://github.com/TommyE123/docker-autoheal/issues/154)) ([489b3ba](https://github.com/TommyE123/docker-autoheal/commit/489b3ba95c905b193f53b3dabfbe463070e741cf))


### Bug Fixes

* enable EditorConfig checker and fix compliance issues ([#161](https://github.com/TommyE123/docker-autoheal/issues/161)) ([8436414](https://github.com/TommyE123/docker-autoheal/commit/84364145a0c8342cbff4359d272cb859d0a6efab))
* enforce timezone-aware UTC event timestamps ([#119](https://github.com/TommyE123/docker-autoheal/issues/119)) ([109b67a](https://github.com/TommyE123/docker-autoheal/commit/109b67a4d91b9239d7b19a434f93262262004571))
* regenerate issue triage workflow with gh-aw 0.88.7 ([#175](https://github.com/TommyE123/docker-autoheal/issues/175)) ([68a1d64](https://github.com/TommyE123/docker-autoheal/commit/68a1d64543c67e3bc1aac5aaf416ffcae56281bf))
* store custom health checks by stable_id instead of the ephemeral container ID ([#148](https://github.com/TommyE123/docker-autoheal/issues/148)) ([2f1afed](https://github.com/TommyE123/docker-autoheal/commit/2f1afed145d9121d38a67be9e16d7c2426d4f83d))


### Chores

* add .editorconfig and .gitattributes ([#153](https://github.com/TommyE123/docker-autoheal/issues/153)) ([ae8ebfa](https://github.com/TommyE123/docker-autoheal/commit/ae8ebfaa84e437e79157e7d809589c76a29b8bec))
* adopt pyright and remove mypy ([#157](https://github.com/TommyE123/docker-autoheal/issues/157)) ([c826d5e](https://github.com/TommyE123/docker-autoheal/commit/c826d5e383cd765d2aec902891d01589843a00c6))
* **deps:** update alpine:latest docker digest to 294b683 ([#182](https://github.com/TommyE123/docker-autoheal/issues/182)) ([a5bdb28](https://github.com/TommyE123/docker-autoheal/commit/a5bdb289c33f4e92b310b63f5ff47dec0bfca88d))
* **deps:** update alpine:latest docker digest to 5b02b42 ([#168](https://github.com/TommyE123/docker-autoheal/issues/168)) ([876c144](https://github.com/TommyE123/docker-autoheal/commit/876c14446e6f5cd375a59fbb8591abd46d573e88))
* **deps:** update codecov/codecov-action action to v7.1.1 ([#186](https://github.com/TommyE123/docker-autoheal/issues/186)) ([ba2d6d3](https://github.com/TommyE123/docker-autoheal/commit/ba2d6d3f496706300fac94d3057b1718851e579a))
* **deps:** update docker/build-push-action action to v7.4.0 ([#102](https://github.com/TommyE123/docker-autoheal/issues/102)) ([9e91d00](https://github.com/TommyE123/docker-autoheal/commit/9e91d0072c78b6529a2d6d7a3d5e1674674ec8ee))
* **deps:** update docker/setup-buildx-action action to v4.4.1 ([#194](https://github.com/TommyE123/docker-autoheal/issues/194)) ([a1e3e4a](https://github.com/TommyE123/docker-autoheal/commit/a1e3e4a30fb47d5043f4eaf566bec05bcf3b994b))
* **deps:** update docker/setup-qemu-action action to v4.4.0 ([#195](https://github.com/TommyE123/docker-autoheal/issues/195)) ([ba5be6b](https://github.com/TommyE123/docker-autoheal/commit/ba5be6bd9fd61ca5561b73db472133a2f6dc4750))
* **deps:** update github/gh-aw-actions action to v0.89.17 ([#196](https://github.com/TommyE123/docker-autoheal/issues/196)) ([542f9c7](https://github.com/TommyE123/docker-autoheal/commit/542f9c74fe8fb48a24dd8a2f413c72020b25e51e))
* **deps:** update nginx:alpine docker digest to 62ff208 ([#190](https://github.com/TommyE123/docker-autoheal/issues/190)) ([ce39335](https://github.com/TommyE123/docker-autoheal/commit/ce39335af37a456e129aef22e0482c8f2cda9942))
* **deps:** update postgres:14-alpine docker digest to 1a91675 ([#171](https://github.com/TommyE123/docker-autoheal/issues/171)) ([1780871](https://github.com/TommyE123/docker-autoheal/commit/17808718419fd6a0aa792061c48089d6a2d1b95b))
* **deps:** update python:3.14-alpine docker digest to 016508b ([#174](https://github.com/TommyE123/docker-autoheal/issues/174)) ([719466b](https://github.com/TommyE123/docker-autoheal/commit/719466bc96f26882e076468502d13908dcc262e6))
* **deps:** update python:3.14-slim docker digest to 0097bb6 ([#187](https://github.com/TommyE123/docker-autoheal/issues/187)) ([aa87952](https://github.com/TommyE123/docker-autoheal/commit/aa8795256b140cca388be7092ebb17ffb3563772))
* **deps:** update python:3.14-slim docker digest to caaf356 ([#193](https://github.com/TommyE123/docker-autoheal/issues/193)) ([8aaeb9c](https://github.com/TommyE123/docker-autoheal/commit/8aaeb9c13b34c927d277a02b9242abf40782ef6f))
* **deps:** update redis:7-alpine docker digest to 520775a ([#176](https://github.com/TommyE123/docker-autoheal/issues/176)) ([d57915f](https://github.com/TommyE123/docker-autoheal/commit/d57915fbd3683331893fd06a59221783dc8a32aa))
* **deps:** update redis:alpine docker digest to bd999b5 ([#185](https://github.com/TommyE123/docker-autoheal/issues/185)) ([1bc3b8a](https://github.com/TommyE123/docker-autoheal/commit/1bc3b8a5c5eb0890d32ae69a3aab47d27cb08a98))
* disable JSON_NPM_PACKAGE_JSON_LINT ([#170](https://github.com/TommyE123/docker-autoheal/issues/170)) ([a4a100d](https://github.com/TommyE123/docker-autoheal/commit/a4a100d69d4ffb9a711982da87d1671adbe55e9f))
* disable redundant MegaLinter security analysers ([#189](https://github.com/TommyE123/docker-autoheal/issues/189)) ([34579a5](https://github.com/TommyE123/docker-autoheal/commit/34579a5e9fb2f11be220c339206318297290445f))
* disable Rumdl and remove redundant GraphQL Biome ([#173](https://github.com/TommyE123/docker-autoheal/issues/173)) ([2584cd0](https://github.com/TommyE123/docker-autoheal/commit/2584cd045e302caf3d5a410f9d8df974aa93fc65))
* disable unused TSX Biome configuration ([#179](https://github.com/TommyE123/docker-autoheal/issues/179)) ([fbece25](https://github.com/TommyE123/docker-autoheal/commit/fbece255e8232cde5db873e65ecce6a56f27478d))
* disable unused TypeScript support ([#172](https://github.com/TommyE123/docker-autoheal/issues/172)) ([9961e30](https://github.com/TommyE123/docker-autoheal/commit/9961e308174192b2ee18d46464a210f3fefb02bf))
* increase Renovate PR throughput limits ([#192](https://github.com/TommyE123/docker-autoheal/issues/192)) ([443d255](https://github.com/TommyE123/docker-autoheal/commit/443d255d77ae6a6b8f27424f3f255849377e2bac))
* label Renovate PRs by update type ([#199](https://github.com/TommyE123/docker-autoheal/issues/199)) ([3d6d209](https://github.com/TommyE123/docker-autoheal/commit/3d6d20927acfad22637df64359fe45725942144d))
* make MegaLinter formatter errors blocking ([#169](https://github.com/TommyE123/docker-autoheal/issues/169)) ([16fe969](https://github.com/TommyE123/docker-autoheal/commit/16fe9690395a185178509fca315e976a05b383bf))
* reduce MegaLinter scope to repository technologies ([#151](https://github.com/TommyE123/docker-autoheal/issues/151)) ([7e3866e](https://github.com/TommyE123/docker-autoheal/commit/7e3866e488f27371acc66743bba53beb903e03e9))
* **release:** configure Release Please changelog sections ([#181](https://github.com/TommyE123/docker-autoheal/issues/181)) ([26c2c18](https://github.com/TommyE123/docker-autoheal/commit/26c2c18e4debdab3d0e9af604f1acc3439bd47b7))
* restrict Ruff to code-quality rules, keep Bandit for security ([#155](https://github.com/TommyE123/docker-autoheal/issues/155)) ([6465ac4](https://github.com/TommyE123/docker-autoheal/commit/6465ac49b0c064bfdf6496a73a0818e7ac768241))
* update Renovate PR label conventions ([#204](https://github.com/TommyE123/docker-autoheal/issues/204)) ([559e32e](https://github.com/TommyE123/docker-autoheal/commit/559e32ea4530b6f79f3720770d80b5a7495c4693))


### Continuous Integration

* replace bespoke release workflow with Release Please ([#150](https://github.com/TommyE123/docker-autoheal/issues/150)) ([798ad9c](https://github.com/TommyE123/docker-autoheal/commit/798ad9ce31775778201bc6b86dee4d4888f88825))

## [2.0.16](https://github.com/TommyE123/docker-autoheal/compare/v2.0.15...v2.0.16) (2026-09-16)

### Documentation

* reorganise and rewrite project documentation ([#23](https://github.com/TommyE123/docker-autoheal/pull/23))

## [2.0.15](https://github.com/TommyE123/docker-autoheal/compare/v2.0.14...v2.0.15) (2026-09-16)

### Documentation

* strengthen Claude guidance for CodeRabbit, Sourcery and MegaLinter ([#147](https://github.com/TommyE123/docker-autoheal/pull/147))

## [2.0.14](https://github.com/TommyE123/docker-autoheal/compare/v2.0.13...v2.0.14) (2026-09-16)

### Miscellaneous Chores

* rationalise Python MegaLinter tools and type checking ([#128](https://github.com/TommyE123/docker-autoheal/pull/128))

## [2.0.13](https://github.com/TommyE123/docker-autoheal/compare/v2.0.12...v2.0.13) (2026-09-16)

### Miscellaneous Chores

* refactor Claude guidance into focused rules and skills ([#145](https://github.com/TommyE123/docker-autoheal/pull/145))

## [2.0.12](https://github.com/TommyE123/docker-autoheal/compare/v2.0.11...v2.0.12) (2026-09-16)

### Miscellaneous Chores

* **deps:** update codecov/codecov-action action to v7.1.0 ([#139](https://github.com/TommyE123/docker-autoheal/pull/139))

## [2.0.11](https://github.com/TommyE123/docker-autoheal/compare/v2.0.10...v2.0.11) (2026-09-16)

### Continuous Integration

* add production smoke test validating real Docker client connection ([#137](https://github.com/TommyE123/docker-autoheal/pull/137))

## [2.0.10](https://github.com/TommyE123/docker-autoheal/compare/v2.0.9...v2.0.10) (2026-09-16)

### Miscellaneous Chores

* **deps:** update dependency docker to v7 ([#61](https://github.com/TommyE123/docker-autoheal/pull/61))

## [2.0.9](https://github.com/TommyE123/docker-autoheal/compare/v2.0.8...v2.0.9) (2026-09-15)

### Bug Fixes

* correct Dockerfile EXPOSE port for the Web UI (8080 -> 3131) ([#36](https://github.com/TommyE123/docker-autoheal/pull/36))

## [2.0.8](https://github.com/TommyE123/docker-autoheal/compare/v2.0.7...v2.0.8) (2026-09-15)

### Bug Fixes

* move misplaced package-init code from `notification_manager.py` to `__init__.py` ([#40](https://github.com/TommyE123/docker-autoheal/pull/40))

## [2.0.7](https://github.com/TommyE123/docker-autoheal/compare/v2.0.6...v2.0.7) (2026-09-15)

### Documentation

* standardise how we request CodeRabbit reviews ([#135](https://github.com/TommyE123/docker-autoheal/pull/135))

## [2.0.6](https://github.com/TommyE123/docker-autoheal/compare/v2.0.5...v2.0.6) (2026-09-15)

### Tests

* add custom health check integration coverage ([#105](https://github.com/TommyE123/docker-autoheal/pull/105))

## [2.0.5](https://github.com/TommyE123/docker-autoheal/compare/v2.0.4...v2.0.5) (2026-09-15)

### Bug Fixes

* replace deprecated aiohttp BasicAuth in UptimeKumaClient ([#97](https://github.com/TommyE123/docker-autoheal/pull/97))

## [2.0.4](https://github.com/TommyE123/docker-autoheal/compare/v2.0.3...v2.0.4) (2026-09-14)

### Code Refactoring

* remove dead code from MonitoringEngine._check_containers() ([#39](https://github.com/TommyE123/docker-autoheal/pull/39))

## [2.0.3](https://github.com/TommyE123/docker-autoheal/compare/v2.0.2...v2.0.3) (2026-09-14)

### Miscellaneous Chores

* tighten Renovate automerge policy ([#124](https://github.com/TommyE123/docker-autoheal/pull/124))

## [2.0.2](https://github.com/TommyE123/docker-autoheal/compare/v2.0.1...v2.0.2) (2026-09-13)

### Miscellaneous Chores

* Fix Hadolint issues in Dockerfiles ([#112](https://github.com/TommyE123/docker-autoheal/pull/112))

## [2.0.1](https://github.com/TommyE123/docker-autoheal/compare/v2.0.0...v2.0.1) (2026-09-13)

### Miscellaneous Chores

* enable YAML v8r ([#123](https://github.com/TommyE123/docker-autoheal/pull/123))

## [2.0.0](https://github.com/TommyE123/docker-autoheal/compare/v2...v2.0.0) (2026-09-13)

### Bug Fixes

* use UTC for unquarantine event timestamp ([#37](https://github.com/TommyE123/docker-autoheal/pull/37))

### Tests

* consolidate duplicated Uptime-Kuma fake client into shared fixture ([#96](https://github.com/TommyE123/docker-autoheal/pull/96))

### Continuous Integration

* separate Docker build and release workflows ([#117](https://github.com/TommyE123/docker-autoheal/pull/117))

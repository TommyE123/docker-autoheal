# Changelog

This file is maintained by [Release Please](https://github.com/googleapis/release-please) as
part of its standing Release PR process. Entries below `v2.0.16` are the project's real,
pre-Release-Please release history (from the repository's existing GitHub Releases), seeded here
so the changelog isn't starting from nothing; entries from this point forward are generated
automatically from Conventional Commit PR titles.

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

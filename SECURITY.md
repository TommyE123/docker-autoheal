# Security policy

## Supported versions

Security fixes are made for the latest release only. If you are running an older version,
update to the latest release first and check whether the problem still applies.

## Reporting a vulnerability

Please do not open a public issue or pull request for a security problem.

Report it privately with GitHub's private vulnerability reporting:

1. Open the [Security tab](https://github.com/TommyE123/docker-autoheal/security) of the
   repository.
2. Choose **Report a vulnerability**, or go straight to
   [the report form](https://github.com/TommyE123/docker-autoheal/security/advisories/new).

Please include as much of this as you can:

* the Docker Auto-Heal version, and whether you run the published image or a build of your own
* how it is deployed, for example how the Docker socket is exposed and which ports are reachable
* steps to reproduce the problem
* what an attacker could do with it

## What to expect

Docker Auto-Heal is maintained by one person, so these are targets and not guarantees:

* an acknowledgement within 7 days
* an update on whether the report is accepted, and a plan for a fix, within 30 days
* a fix published as a new release, with credit in the advisory if you want it

Reports are handled in private until a fixed release is available.

## Scope

In scope:

* the Docker Auto-Heal application, its web UI and its REST API
* the published Docker image and the way it is built

Out of scope:

* vulnerabilities in development tooling, such as the linters and scanners used by the
  Dev Container and MegaLinter. They never ship in the image, and the repository does not
  scan them for dependency vulnerabilities.
* advisories in third-party dependencies that have no effect on Docker Auto-Heal. Shipped
  dependencies are checked by Trivy in CI and updated by Renovate, so please report a
  dependency problem only if you can show it is exploitable through Docker Auto-Heal.

For how dependency vulnerabilities are scanned and handled, see
[Dependency management](docs/maintainer/dependency-management.md).

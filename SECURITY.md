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

* vulnerabilities in the development tooling, such as the linters and scanners. The Dev Container
  tools float to the latest release, and the tools bundled with MegaLinter are fixed by the
  pinned MegaLinter release. None of it ships in the image, and the repository does not scan it
  for dependency vulnerabilities.
* vulnerabilities in the frontend build tools, such as ESLint and Vite, unless they affect the
  built web UI. They are installed from the pinned `frontend/package-lock.json` and run at build
  time, not in the image. Trivy does not report them, but SonarCloud and GitHub's Dependabot
  alerts may, and those findings are handled as ordinary dependency updates.
* advisories in third-party dependencies that have no effect on Docker Auto-Heal. The direct
  runtime dependencies in `requirements.txt` and the production dependencies in the frontend
  lockfile are checked by Trivy in CI and updated by Renovate. The transitive Python packages and
  the operating system packages in the image are not scanned. Please report a dependency problem
  only if you can show it is exploitable through Docker Auto-Heal.

For how dependency vulnerabilities are scanned and handled, see
[Dependency management](docs/maintainer/dependency-management.md).

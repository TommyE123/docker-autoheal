# SonarCloud analysis

SonarCloud analyses the repository from CI, not with Automatic Analysis. The `SonarCloud scan`
step in the `unit-tests` job of `.github/workflows/tests.yml` runs after pytest, so it reads the
`coverage.xml` that pytest already wrote (`sonar.python.coverage.reportPaths` in
`.sonarcloud.properties`). The tests are not run a second time. It runs on pull requests and on
pushes to `main`.

## One-time setup

Do these in order. The scan step is part of the required `unit-tests` check, so it fails, on the
pull request that adds it and on every later run, until all of them are done.

1. Create a SonarCloud token and add it as the `SONAR_TOKEN` repository secret.
2. Add these repository variables (Settings → Secrets and variables → Actions → Variables):
   * `SONAR_ORGANIZATION`: the SonarCloud organization key.
   * `SONAR_PROJECT_KEY`: the SonarCloud project key.
3. In SonarCloud, open **Administration → Analysis Method** and turn Automatic Analysis off.
   While it is on, SonarCloud rejects the CI scan.
4. Re-run the `unit-tests` job.

Open pull requests whose branches lack the scan step get no SonarCloud analysis once Automatic
Analysis is off, until they merge `main`.

## Notes

* The scan is skipped for pull requests from forks, which get no secrets, and for badge-only PRs.
* The checkout uses `fetch-depth: 0` because SonarCloud needs the full history.
* Codecov reporting is separate and unchanged.

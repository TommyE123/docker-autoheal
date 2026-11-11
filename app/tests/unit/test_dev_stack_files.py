"""Contract checks for the dev stack files: the VS Code task and the dev Compose bootstrap.

Kept in a module of their own because they read repository files relative to the repository
root, which does not exist inside ``mutants/``. They import nothing from ``app/`` directly, so
mutation testing ignores this module (see ``pyproject.toml``).
"""

import fnmatch
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_DEV = REPO_ROOT / "docker-compose.dev.yml"
SEED = '{"monitor":{"label_key":"autoheal.dev"}}'


def test_run_docker_stack_task_does_not_detect_an_ip():
    tasks = json.loads((REPO_ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    task = next(t for t in tasks if t["label"] == "Autoheal: Run Docker Stack")

    assert task["command"] == (
        "docker compose -p docker-autoheal-dev -f docker-compose.yml "
        "-f docker-compose.dev.yml up --build autoheal"
    )
    assert "hostname" not in task["command"]


def _bootstrap_script() -> str:
    """The shell script the dev override runs before starting the app (its ``command``)."""
    text = COMPOSE_DEV.read_text(encoding="utf-8")
    block = re.search(r"- sh\n\s+- -c\n\s+- \|\n((?:        .*\n|\n)+)", text)
    assert block, "dev bootstrap command not found in docker-compose.dev.yml"
    return "\n".join(line[8:] for line in block.group(1).split("\n"))


def _run_bootstrap(data_dir: Path, config_text: str | None):
    """Run the real bootstrap against ``data_dir``; the final ``exec`` just prints STARTED."""
    if config_text is not None:
        (data_dir / "config.json").write_text(config_text, encoding="utf-8")
    script = _bootstrap_script()
    script = script.replace("exec python -m app.main", "echo STARTED")
    script = script.replace("python - <<", f"{sys.executable} - <<")
    script = script.replace("/data", str(data_dir))
    # Runs the repo's own bootstrap script with the test interpreter and temp paths substituted.
    return subprocess.run(  # noqa: S603
        ["sh", "-c", script],  # noqa: S607 - PATH is fixed to /usr/bin:/bin below
        cwd=data_dir if data_dir.exists() else data_dir.parent,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
class TestDevBootstrapFailsClosed:
    """The dev container must never start with the production ``autoheal=true`` label."""

    def test_first_start_seeds_the_dev_label_and_starts(self, tmp_path):
        result = _run_bootstrap(tmp_path, None)

        assert result.returncode == 0, result.stderr
        assert "STARTED" in result.stdout
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == SEED
        assert not (tmp_path / "config.json.tmp").exists()

    def test_valid_existing_config_is_kept_unchanged(self, tmp_path):
        # A legitimate user change to the monitoring label is preserved, not re-seeded.
        custom = '{"monitor":{"label_key":"my.dev","label_value":"yes"},"restart":{"mode":"both"}}'

        result = _run_bootstrap(tmp_path, custom)

        assert result.returncode == 0, result.stderr
        assert "STARTED" in result.stdout
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == custom

    @pytest.mark.parametrize(
        "config_text",
        [
            pytest.param('{"monitor":{"label_key":"autoh', id="malformed-json"),
            pytest.param("", id="empty-file"),
            pytest.param("[]", id="not-an-object"),
            pytest.param('{"restart":{"mode":"both"}}', id="monitor-section-missing"),
            pytest.param('{"monitor":"autoheal.dev"}', id="monitor-wrong-type"),
            pytest.param(
                '{"monitor":{"label_key":"autoheal.dev","interval_seconds":0}}',
                id="monitor-has-an-invalid-field",
            ),
            pytest.param('{"monitor":{}}', id="defaults-to-the-production-label"),
            pytest.param(
                '{"monitor":{"label_key":"autoheal","label_value":"true"}}',
                id="explicit-production-label",
            ),
        ],
    )
    def test_unusable_existing_config_stops_the_container(self, tmp_path, config_text):
        result = _run_bootstrap(tmp_path, config_text)

        assert result.returncode != 0
        assert "STARTED" not in result.stdout
        assert "Refusing to start" in result.stderr
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == config_text

    def test_failed_seed_stops_the_container(self, tmp_path):
        result = _run_bootstrap(tmp_path / "missing", None)

        assert result.returncode != 0
        assert "STARTED" not in result.stdout


def _renovate_group_minimum(group_name):
    """Return minimumGroupSize of the Renovate rule that sets ``group_name``."""
    rules = json.loads((REPO_ROOT / "renovate.json").read_text(encoding="utf-8"))["packageRules"]
    sizes = [rule["minimumGroupSize"] for rule in rules if rule.get("groupName") == group_name]
    assert sizes, f"No Renovate rule with groupName {group_name!r} found in renovate.json"
    return sizes[0]


def test_python_runtime_group_has_no_release_age_after_catch_all_rule():
    """The Python runtime Renovate group has no release age and follows the catch-all rule."""
    rules = json.loads((REPO_ROOT / "renovate.json").read_text(encoding="utf-8"))["packageRules"]
    group = next(i for i, r in enumerate(rules) if r.get("groupName") == "Python runtime")
    catch_all = next(i for i, r in enumerate(rules) if r.get("matchPackageNames") == ["*"])

    assert rules[group]["minimumReleaseAge"] is None
    assert group > catch_all

    python_names = set(rules[group]["matchPackageNames"])
    python_managers = {"dockerfile", "devcontainer", "custom.regex"}
    for later in rules[group + 1 :]:
        if "minimumReleaseAge" not in later:
            continue
        names = set(later.get("matchPackageNames", []))
        managers = set(later.get("matchManagers", []))
        scoped_away = (names and names.isdisjoint(python_names | {"*"})) or (
            managers and managers.isdisjoint(python_managers)
        )
        assert scoped_away, f"Rule after the Python group could set its release age: {later}"


def test_python_runtime_versions_are_aligned():
    """All Python runtime and tooling targets must use the same version."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    devcontainer = (REPO_ROOT / ".devcontainer" / "Dockerfile").read_text(encoding="utf-8")
    sonar = (REPO_ROOT / ".sonarcloud.properties").read_text(encoding="utf-8")
    pyright = (REPO_ROOT / "pyrightconfig.json").read_text(encoding="utf-8")
    ruff = (REPO_ROOT / ".linter-rules" / ".ruff.toml").read_text(encoding="utf-8")

    docker_version = re.search(
        r"^FROM python:(\d+\.\d+)-slim(?:@|\s|$)",
        dockerfile,
        re.MULTILINE,
    )
    devcontainer_version = re.search(
        r"^FROM mcr\.microsoft\.com/devcontainers/python:"
        r"(\d+\.\d+)-bookworm(?:@|\s|$)",
        devcontainer,
        re.MULTILINE,
    )
    sonar_version = re.search(
        r"^sonar\.python\.version=(\d+\.\d+)$",
        sonar,
        re.MULTILINE,
    )
    pyright_version = re.search(
        r'^\s*"pythonVersion"\s*:\s*"(\d+\.\d+)"',
        pyright,
        re.MULTILINE,
    )
    ruff_version = re.search(
        r'^target-version\s*=\s*"(py\d+)"$',
        ruff,
        re.MULTILINE,
    )

    assert docker_version, "Python version not found in Dockerfile"
    assert devcontainer_version, "Python version not found in Dev Container"
    assert sonar_version, "Python version not found in SonarCloud configuration"
    assert pyright_version, "Python version not found in pyrightconfig.json"
    assert ruff_version, "Ruff target-version not found"

    versions = {
        "Dockerfile": docker_version.group(1),
        "Dev Container": devcontainer_version.group(1),
        "SonarCloud": sonar_version.group(1),
        "Pyright": pyright_version.group(1),
    }

    assert len(set(versions.values())) == 1, f"Python runtime versions are inconsistent: {versions}"

    # Renovate groups the pins above plus Ruff's. A minimum that does not equal that count means
    # the grouped pull request is never created, with no error, or a partial one is allowed.
    assert _renovate_group_minimum("Python runtime") == len(versions) + 1

    expected_ruff_version = f"py{docker_version.group(1).replace('.', '')}"
    assert ruff_version.group(1) == expected_ruff_version, (
        f"Ruff target-version is {ruff_version.group(1)}, expected {expected_ruff_version}"
    )


def test_node_runtime_versions_are_aligned():
    """The Node major must be the same in the build image, CI and the Dev Container."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    devcontainer = (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")

    docker_version = re.search(r"^FROM node:(\d+)-alpine(?:@|\s|$)", dockerfile, re.MULTILINE)
    feature_options = re.search(
        r'"ghcr\.io/devcontainers/features/node:\d+"\s*:\s*\{([^}]*)\}',
        devcontainer,
    )
    feature_version = (
        re.search(r'"version"\s*:\s*"(\d+)"', feature_options.group(1)) if feature_options else None
    )

    assert docker_version, "Node version not found in Dockerfile"
    assert feature_version, "Node version not found in the Dev Container node feature"

    versions = {
        "Dockerfile": docker_version.group(1),
        "Dev Container": feature_version.group(1),
    }
    for workflow in ("tests.yml", "production-smoke-test.yml"):
        text = (REPO_ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        found = re.findall(r"^\s*node-version:\s*(\d+)\s*$", text, re.MULTILINE)
        assert found, f"node-version not found in {workflow}"
        for index, version in enumerate(found, start=1):
            versions[f"{workflow} #{index}"] = version

    assert len(set(versions.values())) == 1, f"Node versions are inconsistent: {versions}"

    # Same reasoning as the Python group: the minimum must equal the number of pins.
    assert _renovate_group_minimum("Node runtime") == len(versions)

    # The docs name the Node major too (prerequisites, Dev Container, build stage). Renovate does
    # not edit prose, so a bump would otherwise leave them stale. Kept out of ``versions`` above
    # because that mapping's size is the number of pins Renovate groups.
    doc_files = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CONTRIBUTING.md",
        *sorted((REPO_ROOT / "docs").rglob("*.md")),
    ]
    stale_docs = {}
    mentions = 0
    for doc in doc_files:
        text = doc.read_text(encoding="utf-8")
        for number in re.findall(r"\bNode(?:\.js)?\s+(\d+)\b", text):
            mentions += 1
            if number != docker_version.group(1):
                stale_docs.setdefault(str(doc.relative_to(REPO_ROOT)), set()).add(number)

    assert mentions, "no Node version found in the documentation"
    assert not stale_docs, (
        f"Documentation names a Node major other than {docker_version.group(1)}: {stale_docs}"
    )


@pytest.mark.parametrize(
    "path",
    [
        ".devcontainer/devcontainer.json",
        ".devcontainer/Dockerfile",
        ".linter-rules/.ruff.toml",
        ".sonarcloud.properties",
        "pyrightconfig.json",
    ],
)
def test_renovate_does_not_ignore_files_holding_runtime_pins(path):
    """A runtime pin in an ignored file is never updated, and silently falls behind."""
    config = json.loads((REPO_ROOT / "renovate.json").read_text(encoding="utf-8"))

    # Renovate ignores a file when the pattern is a substring of its path or a minimatch glob.
    # fnmatch is not minimatch (``*`` also crosses ``/`` here), but it agrees for the globs used
    # in ignorePaths, which is enough to catch ``.devcontainer/**`` or ``.devcontainer`` coming back.
    hiding = [glob for glob in config["ignorePaths"] if glob in path or fnmatch.fnmatch(path, glob)]

    assert not hiding, (
        f"renovate.json ignorePaths {hiding} hides {path}, so Renovate cannot update it"
    )


def test_renovate_ruff_manager_finds_the_ruff_target_version():
    """The group minimum counts Ruff's pin, so Renovate's patterns must really match its file."""
    config = json.loads((REPO_ROOT / "renovate.json").read_text(encoding="utf-8"))
    manager = next(
        m for m in config["customManagers"] if any("ruff" in p for p in m["managerFilePatterns"])
    )
    ruff = (REPO_ROOT / ".linter-rules" / ".ruff.toml").read_text(encoding="utf-8")

    # Renovate wraps file patterns in slashes and uses JavaScript named groups (?<name>...).
    file_pattern = manager["managerFilePatterns"][0]
    assert file_pattern.startswith("/")
    assert file_pattern.endswith("/")
    assert re.search(file_pattern[1:-1], ".linter-rules/.ruff.toml")

    pattern = re.sub(r"\(\?<(?![=!])", "(?P<", manager["matchStrings"][0])
    found = re.search(pattern, ruff)
    assert found, "Renovate's matchStrings do not match target-version in .ruff.toml"
    assert re.search(
        rf'^target-version\s*=\s*"py{found.group("major")}{found.group("minor")}"',
        ruff,
        re.MULTILINE,
    )

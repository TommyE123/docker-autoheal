"""Behaviour checks for the Weekly Maintainer evidence digest script.

The script appends the core source text to the agent's prompt so the agent cannot skip
reading it. These tests run it against a small synthetic checkout and pin down what the
workflow relies on: the per-run token appears at both ends, source files are inlined in
priority order until the byte cap, and any problem fails the step instead of leaving the
agent without a digest.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "weekly-maintainer-digest.sh"

ENGINE = "app/monitor/monitoring_engine.py"
DOCKER = "app/docker_client/docker_client_wrapper.py"
HEALTH = "app/monitor/health.py"


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    _write(tmp_path, ENGINE, "ENGINE_BODY = 1\n" + "x" * 100 + "\n")
    _write(tmp_path, DOCKER, "DOCKER_BODY = 1\n" + "y" * 100 + "\n")
    _write(tmp_path, HEALTH, "HEALTH_BODY = 1\n")
    _write(tmp_path, "app/api/api.py", "API_BODY = 1\n")
    _write(tmp_path, "app/tests/unit/test_engine.py", "from app.monitor import monitoring_engine\n")
    _write(tmp_path, ".github/workflows/tests.yml", "name: tests\n")
    _write(tmp_path, ".github/workflows/weekly-maintainer.lock.yml", "generated\n")
    _write(tmp_path, "renovate.json", "{}\n")
    (tmp_path / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")
    return tmp_path


def _run(checkout: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607 - PATH is fixed to /usr/bin:/bin below
        cwd=checkout,
        env={"PATH": "/usr/bin:/bin", "PROMPT_FILE": str(checkout / "prompt.txt"), **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_appends_digest_with_matching_token_at_both_ends(checkout: Path):
    result = _run(checkout)

    assert result.returncode == 0, result.stderr
    prompt = (checkout / "prompt.txt").read_text(encoding="utf-8")
    assert prompt.startswith("ORIGINAL PROMPT\n")
    tokens = re.findall(r"^DIGEST_TOKEN: ([0-9a-f]{12})$", prompt, re.MULTILINE)
    assert len(tokens) == 2
    assert tokens[0] == tokens[1]
    assert prompt.index("===== DIGEST START =====") < prompt.index("===== DIGEST END =====")


def _token(checkout: Path) -> str:
    match = re.search(r"DIGEST_TOKEN: (\w+)", (checkout / "prompt.txt").read_text(encoding="utf-8"))
    assert match is not None
    return match.group(1)


def test_token_differs_between_runs(checkout: Path):
    _run(checkout)
    first = _token(checkout)
    (checkout / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")
    _run(checkout)

    assert first != _token(checkout)


def test_inlines_priority_files_in_order_and_marks_them_in_the_inventory(checkout: Path):
    _run(checkout)

    prompt = (checkout / "prompt.txt").read_text(encoding="utf-8")
    assert f"{ENGINE} " in prompt
    assert re.search(rf"^{re.escape(ENGINE)} \d+ INLINE$", prompt, re.MULTILINE)
    assert prompt.index(f"===== FILE: {ENGINE}") < prompt.index(f"===== FILE: {DOCKER}")
    assert prompt.index(f"===== FILE: {DOCKER}") < prompt.index(f"===== FILE: {HEALTH}")
    assert "ENGINE_BODY = 1" in prompt
    # Not a priority file: listed in the inventory, but its text stays out.
    assert re.search(r"^app/api/api.py \d+$", prompt, re.MULTILINE)
    assert "API_BODY" not in prompt


def test_inventory_lists_tests_with_imported_modules_and_skips_lock_files(checkout: Path):
    _run(checkout)

    prompt = (checkout / "prompt.txt").read_text(encoding="utf-8")
    assert re.search(r"^app/tests/unit/test_engine.py \d+ app.monitor\s*$", prompt, re.MULTILINE)
    assert ".github/workflows/tests.yml " in prompt
    assert "renovate.json " in prompt
    assert "weekly-maintainer.lock.yml" not in prompt


def _inlined(checkout: Path) -> list[str]:
    prompt = (checkout / "prompt.txt").read_text(encoding="utf-8")
    return re.findall(r"^===== FILE: (\S+) ", prompt, re.MULTILINE)


def test_byte_cap_skips_a_file_that_does_not_fit_but_keeps_later_small_ones(checkout: Path):
    # Engine and Docker files are about 117 bytes each, health is 15: a cap of 150 fits the
    # engine, skips Docker, and still fits health.
    result = _run(checkout, INLINE_CAP="150")

    assert result.returncode == 0, result.stderr
    assert _inlined(checkout) == [ENGINE, HEALTH]
    prompt = (checkout / "prompt.txt").read_text(encoding="utf-8")
    assert re.search(rf"^{re.escape(DOCKER)} \d+$", prompt, re.MULTILINE)


def test_byte_cap_is_inclusive(checkout: Path):
    sizes = {name: (checkout / name).stat().st_size for name in (ENGINE, DOCKER, HEALTH)}
    exact = sizes[ENGINE] + sizes[DOCKER] + sizes[HEALTH]

    _run(checkout, INLINE_CAP=str(exact))
    assert _inlined(checkout) == [ENGINE, DOCKER, HEALTH]

    (checkout / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")
    _run(checkout, INLINE_CAP=str(exact - 1))
    assert _inlined(checkout) == [ENGINE, DOCKER]


def test_zero_cap_inlines_nothing_and_still_succeeds(checkout: Path):
    result = _run(checkout, INLINE_CAP="0")

    assert result.returncode == 0, result.stderr
    assert _inlined(checkout) == []
    assert "DIGEST_TOKEN" in (checkout / "prompt.txt").read_text(encoding="utf-8")


def test_prompt_limit_is_inclusive(checkout: Path):
    _run(checkout)
    exact = (checkout / "prompt.txt").stat().st_size
    (checkout / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")

    # The token is fixed length, so the same input gives the same size on every run.
    assert _run(checkout, PROMPT_LIMIT=str(exact)).returncode == 0

    (checkout / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")
    assert _run(checkout, PROMPT_LIMIT=str(exact - 1)).returncode != 0


@pytest.mark.parametrize("missing", ["app/tests/unit", "app"])
def test_fails_when_a_source_directory_is_missing(checkout: Path, missing: str):
    shutil.rmtree(checkout / missing)

    result = _run(checkout)

    assert result.returncode != 0
    assert "not found" in result.stderr
    assert (checkout / "prompt.txt").read_text(encoding="utf-8") == "ORIGINAL PROMPT\n"


def test_fails_when_the_prompt_file_is_missing(checkout: Path):
    (checkout / "prompt.txt").unlink()

    result = _run(checkout)

    assert result.returncode != 0
    assert "not found" in result.stderr


def test_fails_and_leaves_the_prompt_alone_when_it_would_exceed_the_limit(checkout: Path):
    result = _run(checkout, PROMPT_LIMIT="100")

    assert result.returncode != 0
    assert "over the 100 limit" in result.stderr
    assert (checkout / "prompt.txt").read_text(encoding="utf-8") == "ORIGINAL PROMPT\n"

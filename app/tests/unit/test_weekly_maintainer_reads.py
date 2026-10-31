"""Behaviour checks for the Weekly Maintainer source read plan script.

The script appends to the agent's prompt the exact "cat -n" commands that read every app
source file, in three parts. These tests run it against a small synthetic checkout and pin
down what the workflow relies on: the plan covers exactly the files the coverage check
counts, in the forms that check accepts, large files are split so no command's output is
cut, and any problem fails the step instead of leaving the agent without a plan.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / ".github" / "scripts"
READS = SCRIPTS / "weekly-maintainer-reads.sh"
COVERAGE = SCRIPTS / "weekly-maintainer-coverage.sh"

LARGE = "app/monitor/monitoring_engine.py"
# 1,500 lines of about 40 bytes: over the 30,000-byte split point, read in three parts.
LARGE_TEXT = "".join(f"engine_line_{n:04d} = {n:010d}  # padding\n" for n in range(1, 1501))


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    for n in range(12):
        _write(tmp_path, f"app/api/module_{n:02d}.py", f"VALUE = {n}\n")
    _write(tmp_path, LARGE, LARGE_TEXT)
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/tests/unit/test_api.py", "TEST = 1\n")
    (tmp_path / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")
    return tmp_path


def _run(checkout: Path, script: Path = READS, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(script)],  # noqa: S607 - PATH is fixed to /usr/bin:/bin below
        cwd=checkout,
        env={"PATH": "/usr/bin:/bin", "PROMPT_FILE": str(checkout / "prompt.txt"), **env},
        capture_output=True,
        text=True,
        check=False,
    )


def _plan(checkout: Path) -> str:
    prompt = (checkout / "prompt.txt").read_text(encoding="utf-8")
    assert prompt.startswith("ORIGINAL PROMPT\n")
    start = prompt.index("===== SOURCE READS START =====")
    return prompt[start : prompt.index("===== SOURCE READS END =====")]


def _commands(plan: str) -> list[str]:
    return [line for line in plan.splitlines() if line.startswith("cat -n ")]


def _parts(plan: str) -> list[list[str]]:
    parts: list[list[str]] = []
    for line in plan.splitlines():
        if line.startswith("Part "):
            parts.append([])
        elif line.startswith("cat -n "):
            parts[-1].append(line)
    return parts


def test_plan_lists_every_source_file_in_three_parts(checkout: Path):
    result = _run(checkout)

    assert result.returncode == 0, result.stderr
    plan = _plan(checkout)
    files = {re.match(r"cat -n (\S+)", command).group(1) for command in _commands(plan)}  # type: ignore[union-attr]
    assert files == {f"app/api/module_{n:02d}.py" for n in range(12)} | {LARGE}
    assert "app/__init__.py" not in plan
    assert "app/tests" not in plan
    assert [len(part) for part in _parts(plan)] == [8, 4, 3]


def test_large_file_is_split_into_joined_600_line_parts(checkout: Path):
    _run(checkout)

    large = [command for command in _commands(_plan(checkout)) if LARGE in command]
    assert large == [
        f"cat -n {LARGE} | head -n 600",
        f"cat -n {LARGE} | head -n 1200 | tail -n +601",
        f"cat -n {LARGE} | tail -n +1201",
    ]


def _coverage_of_planned_run(checkout: Path) -> subprocess.CompletedProcess[str]:
    lines = []
    for number, command in enumerate(_commands(_plan(checkout))):
        tool_id = f"run_shell_command__call_{number}"
        lines.append(
            json.dumps(
                {
                    "type": "tool_use",
                    "tool_name": "run_shell_command",
                    "tool_id": tool_id,
                    "parameters": {"command": command},
                }
            )
        )
        lines.append(json.dumps({"type": "tool_result", "tool_id": tool_id, "status": "success"}))
    (checkout / "agent.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (checkout / "output.json").write_text(json.dumps({"items": [], "errors": []}), encoding="utf-8")
    return _run(
        checkout,
        COVERAGE,
        AGENT_LOG=str(checkout / "agent.log"),
        AGENT_OUTPUT=str(checkout / "output.json"),
        GITHUB_STEP_SUMMARY=str(checkout / "summary.md"),
    )


def test_coverage_check_accepts_a_run_of_exactly_the_planned_commands(checkout: Path):
    _run(checkout)

    result = _coverage_of_planned_run(checkout)

    assert result.returncode == 0, result.stderr
    assert "Read 13 of 13 app source files" in (checkout / "summary.md").read_text(encoding="utf-8")


def _lines(count: int, final_newline: bool = True) -> str:
    text = "".join(f"line_{n:04d} = {n:020d}  # padding padding\n" for n in range(1, count + 1))
    return text if final_newline else text[:-1]


@pytest.mark.parametrize(
    ("text", "expected_parts"),
    [
        pytest.param(_lines(600), 1, id="600-lines-split-into-one-part"),
        pytest.param(_lines(1200), 2, id="1200-lines"),
        pytest.param(_lines(1201, final_newline=False), 3, id="1201-lines-no-final-newline"),
        pytest.param(_lines(1200, final_newline=False), 2, id="1200-lines-no-final-newline"),
        pytest.param(_lines(601, final_newline=False), 2, id="601-lines-no-final-newline"),
    ],
)
def test_split_boundaries_are_fully_covered(checkout: Path, text: str, expected_parts: int):
    _write(checkout, LARGE, text)

    result = _run(checkout)

    assert result.returncode == 0, result.stderr
    large = [command for command in _commands(_plan(checkout)) if LARGE in command]
    assert len(large) == expected_parts
    coverage = _coverage_of_planned_run(checkout)
    assert coverage.returncode == 0, coverage.stderr


def test_small_byte_file_with_long_cat_n_output_is_split(checkout: Path):
    # 4,400 lines of 6 bytes: 26,400 bytes, but cat -n adds 7 characters a line.
    _write(checkout, LARGE, "x = 1\n" * 4400)

    _run(checkout)

    large = [command for command in _commands(_plan(checkout)) if LARGE in command]
    assert len(large) > 1
    assert _coverage_of_planned_run(checkout).returncode == 0


@pytest.mark.parametrize("name", ["app/a;b.py", "app/a b.py", "app/a$b.py"])
def test_unsafe_source_path_fails_the_step(checkout: Path, name: str):
    _write(checkout, name, "VALUE = 1\n")

    result = _run(checkout)

    assert result.returncode == 1
    assert "Unsafe source path" in result.stderr
    assert "SOURCE READS" not in (checkout / "prompt.txt").read_text(encoding="utf-8")


def test_no_source_files_fails_the_step(tmp_path: Path):
    _write(tmp_path, "app/__init__.py", "")
    (tmp_path / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "No app source files found" in result.stderr


def test_part_over_the_cut_fails_the_step(checkout: Path):
    # 700 lines of about 100 bytes: a 600-line part prints about 64,000 characters.
    _write(checkout, LARGE, "".join(f"x_{n:04d} = '{'y' * 90}'\n" for n in range(700)))

    result = _run(checkout)

    assert result.returncode == 1
    assert "over the 40000-character cut" in result.stderr
    assert "SOURCE READS" not in (checkout / "prompt.txt").read_text(encoding="utf-8")


def test_missing_prompt_file_fails_the_step(checkout: Path):
    (checkout / "prompt.txt").unlink()

    result = _run(checkout)

    assert result.returncode == 1
    assert "Prompt file" in result.stderr


def test_fails_outside_the_checkout_root(tmp_path: Path):
    (tmp_path / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "Directory app not found" in result.stderr

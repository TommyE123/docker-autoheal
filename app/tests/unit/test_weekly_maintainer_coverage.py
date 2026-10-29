"""Behaviour checks for the Weekly Maintainer source coverage script.

The script counts which app source files the agent read with "cat -n" according to the
agent log, instead of trusting the agent's own claim. These tests run it against a small
synthetic checkout and log and pin down what the workflow relies on: full coverage passes,
a skipped, failed or redirected read fails the step, and an issue is withheld when the
audit is incomplete.
"""

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3] / ".github" / "scripts" / "weekly-maintainer-coverage.sh"
)

SMALL = "app/api/api.py"
LARGE = "app/monitor/monitoring_engine.py"
FINDING = {"type": "create_issue", "title": "Add a test", "body": "Problem"}
# 1,500 lines: about 55,000 characters with cat -n, so one whole read is cut by Gemini CLI,
# while 600-line and 900-line parts stay under its 40,000-character limit.
LARGE_TEXT = "".join(f"engine_line_{n:04d} = {n:010d}\n" for n in range(1, 1501))
HEAD = f"cat -n {LARGE} | head -n 600"
MIDDLE = f"cat -n {LARGE} | head -n 1200 | tail -n +601"
TAIL_601 = f"cat -n {LARGE} | tail -n +601"
TAIL_1201 = f"cat -n {LARGE} | tail -n +1201"


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    _write(tmp_path, SMALL, "API = 1\n")
    _write(tmp_path, LARGE, LARGE_TEXT)
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/tests/unit/test_api.py", "TEST = 1\n")
    _write(tmp_path, "output.json", json.dumps({"items": [FINDING], "errors": []}))
    return tmp_path


def _log(checkout: Path, *calls: tuple[str, str]) -> None:
    lines = ["[INFO] plain text the parser must skip"]
    for number, (command, status) in enumerate(calls):
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
        lines.append(json.dumps({"type": "tool_result", "tool_id": tool_id, "status": status}))
    (checkout / "agent.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(checkout: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607 - PATH is fixed to /usr/bin:/bin below
        cwd=checkout,
        env={
            "PATH": "/usr/bin:/bin",
            "AGENT_LOG": str(checkout / "agent.log"),
            "AGENT_OUTPUT": str(checkout / "output.json"),
            "GITHUB_STEP_SUMMARY": str(checkout / "summary.md"),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _items(checkout: Path) -> list[dict]:
    return json.loads((checkout / "output.json").read_text(encoding="utf-8"))["items"]


def _summary(checkout: Path) -> str:
    return (checkout / "summary.md").read_text(encoding="utf-8")


def test_full_coverage_passes_and_keeps_the_issue(checkout: Path):
    _log(
        checkout,
        (f"cat -n {SMALL}", "success"),
        (HEAD, "success"),
        (TAIL_601, "success"),
    )

    result = _run(checkout)

    assert result.returncode == 0, result.stderr
    assert "Read 2 of 2 app source files" in _summary(checkout)
    assert _items(checkout) == [FINDING]


def test_skipped_file_fails_and_withholds_the_issue(checkout: Path):
    _log(checkout, (f"cat -n {SMALL}", "success"))

    result = _run(checkout)

    assert result.returncode == 1
    assert "read 1 of 2 app source files" in result.stderr
    summary = _summary(checkout)
    assert "Read 1 of 2 app source files" in summary
    assert f"- {LARGE}" in summary
    items = _items(checkout)
    assert [item["type"] for item in items] == ["noop"]
    assert items[0]["message"].startswith("INCOMPLETE AUDIT:")


def test_noop_output_is_left_alone_when_coverage_is_incomplete(checkout: Path):
    noop = {"type": "noop", "message": "NO FINDING: nothing"}
    (checkout / "output.json").write_text(
        json.dumps({"items": [noop], "errors": []}), encoding="utf-8"
    )
    _log(checkout)

    result = _run(checkout)

    assert result.returncode == 1
    assert _items(checkout) == [noop]


def test_three_parts_that_join_up_count(checkout: Path):
    _log(
        checkout,
        (f"cat -n {SMALL}", "success"),
        (TAIL_1201, "success"),
        (MIDDLE, "success"),
        (HEAD, "success"),
    )

    assert _run(checkout).returncode == 0


def test_malformed_log_lines_are_skipped(checkout: Path):
    _log(checkout, (f"cat -n {SMALL}", "success"), (HEAD, "success"), (TAIL_601, "success"))
    with (checkout / "agent.log").open("a", encoding="utf-8") as log:
        log.write('{\n{"type": "tool_use", "tool_name": "run_shell\n')

    result = _run(checkout)

    assert result.returncode == 0, result.stderr
    assert "Read 2 of 2 app source files" in _summary(checkout)


@pytest.mark.parametrize(
    "calls",
    [
        pytest.param([(HEAD, "success"), (TAIL_601, "error")], id="failed-call"),
        pytest.param([(f"{HEAD} > /dev/null", "success"), (TAIL_601, "success")], id="redirected"),
        pytest.param([(HEAD, "success")], id="first-part-only"),
        pytest.param([(MIDDLE, "success"), (TAIL_1201, "success")], id="first-part-missing"),
        pytest.param([(HEAD, "success"), (TAIL_1201, "success")], id="gap-between-parts"),
        pytest.param(
            [(HEAD, "success"), (f"cat -n {LARGE} | tail -n +99999", "success")], id="tail-past-end"
        ),
        pytest.param([(f"cat -n {LARGE}", "success")], id="whole-read-over-the-cut"),
        pytest.param([(f"cat {LARGE}", "success")], id="without-line-numbers"),
    ],
)
def test_reads_that_do_not_count(checkout: Path, calls: list[tuple[str, str]]):
    _log(checkout, (f"cat -n {SMALL}", "success"), *calls)

    result = _run(checkout)

    assert result.returncode == 1
    assert f"- {LARGE}" in _summary(checkout)


def test_missing_log_counts_as_nothing_read(checkout: Path):
    result = _run(checkout)

    assert result.returncode == 1
    assert "Read 0 of 2 app source files" in _summary(checkout)


def test_fails_outside_the_checkout_root(tmp_path: Path):
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607 - PATH is fixed to /usr/bin:/bin below
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Directory app not found" in result.stderr

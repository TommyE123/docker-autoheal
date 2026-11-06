"""Behaviour checks for the Documentation Drift Detection read plan and coverage scripts.

The read plan script picks one focus area a week, appends the exact "cat -n" commands that read
its documentation and source files to the agent's prompt, and passes the week number on through
GITHUB_ENV. The coverage script rebuilds the same file list from that week number and the
checkout (nothing the agent can write decides it), counts from the agent's own tool log which
of those files were really read, and withholds a pull request when the audit is incomplete. These tests run both
against the real repository (so a renamed document or module breaks here, not in a weekly run)
and against a small synthetic checkout, and pin down what the workflow relies on.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
READS = ROOT / ".github" / "scripts" / "docs-drift-reads.sh"
COVERAGE = ROOT / ".github" / "scripts" / "docs-drift-coverage.sh"

# Weeks 10 to 14 have the last digits 0 to 4, so they reach each area once.
AREAS = {
    10: "Configuration and deployment",
    11: "Health checks and recovery",
    12: "API, UI and architecture",
    13: "Metrics, logging and troubleshooting",
    14: "Notifications and Uptime Kuma",
}

# The synthetic checkout is shaped for the last area (week 4 or 9).
LARGE = "app/notifications/notification_manager.py"
SMALL = "app/uptime_kuma/matching.py"
PR = {"type": "create_pull_request", "title": "Fix a document", "body": "Drift"}
# 1,500 lines: about 55,000 characters with cat -n, so one whole read is cut by Gemini CLI,
# while 600-line and 900-line parts stay under its 40,000-character limit.
LARGE_TEXT = "".join(f"manager_line_{n:04d} = {n:010d}\n" for n in range(1, 1501))
HEAD = f"cat -n {LARGE} | head -n 600"
MIDDLE = f"cat -n {LARGE} | head -n 1200 | tail -n +601"
TAIL_601 = f"cat -n {LARGE} | tail -n +601"
TAIL_1201 = f"cat -n {LARGE} | tail -n +1201"
SYNTHETIC_FILES = {
    "README.md": "# Readme\n",
    "docs/user/notifications.md": "# Notifications\n",
    LARGE: LARGE_TEXT,
    "app/notifications/__init__.py": "",
    SMALL: "MATCH = 1\n",
    "app/uptime_kuma/uptime_kuma_client.py": "CLIENT = 1\n",
    "app/monitor/uptime_kuma_monitor.py": "MONITOR = 1\n",
    "app/tests/unit/test_matching.py": "TEST = 1\n",
}


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    for relative, text in SYNTHETIC_FILES.items():
        _write(tmp_path, relative, text)
    (tmp_path / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")
    _write(tmp_path, "output.json", json.dumps({"items": [PR], "errors": []}))
    return tmp_path


def _reads(cwd: Path, week: int | str, work: Path) -> subprocess.CompletedProcess[str]:
    """Runs the read plan script in cwd, writing the prompt and the job environment file under work."""
    prompt = work / "prompt.txt"
    if not prompt.exists():
        prompt.write_text("ORIGINAL PROMPT\n", encoding="utf-8")
    return subprocess.run(  # noqa: S603
        ["bash", str(READS)],  # noqa: S607 - PATH is fixed to /usr/bin:/bin below
        cwd=cwd,
        env={
            "PATH": "/usr/bin:/bin",
            "PROMPT_FILE": str(prompt),
            "GITHUB_ENV": str(work / "env.txt"),
            "WEEK": str(week),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _plan(work: Path) -> str:
    prompt = (work / "prompt.txt").read_text(encoding="utf-8")
    assert prompt.startswith("ORIGINAL PROMPT\n")
    start = prompt.index("===== READS START =====")
    return prompt[start : prompt.index("===== READS END =====")]


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


def _manifest(work: Path) -> tuple[str, list[str]]:
    """The focus area name and the files of the plan, in reading order, from the prompt."""
    plan = _plan(work)
    heading = re.search(r"Focus area this week: (.+) \(ISO week \d+\)\.", plan)
    assert heading
    files: list[str] = []
    for command in _commands(plan):
        name = re.match(r"cat -n (\S+)", command).group(1)  # type: ignore[union-attr]
        if name not in files:
            files.append(name)
    return heading.group(1), files


@pytest.mark.parametrize(("week", "area"), AREAS.items())
def test_every_area_resolves_against_the_real_repository(tmp_path: Path, week: int, area: str):
    result = _reads(ROOT, week, tmp_path)

    assert result.returncode == 0, result.stderr
    name, files = _manifest(tmp_path)
    assert name == area
    assert files[0] == "README.md"
    assert all((ROOT / f).is_file() for f in files)
    assert not any(f.startswith("app/tests") for f in files)
    assert len(files) == len(set(files))
    assert f"Focus area this week: {area} (ISO week {week})." in _plan(tmp_path)
    assert (tmp_path / "env.txt").read_text(encoding="utf-8") == f"DOCS_DRIFT_WEEK={week}\n"


def test_areas_together_cover_every_user_document_and_source_directory(tmp_path: Path):
    covered: set[str] = set()
    for week in AREAS:
        work = tmp_path / str(week)
        work.mkdir()
        assert _reads(ROOT, week, work).returncode == 0
        covered.update(_manifest(work)[1])

    user_docs = {p.relative_to(ROOT).as_posix() for p in (ROOT / "docs" / "user").glob("*.md")}
    assert user_docs <= covered
    for directory in ("api", "config", "docker_client", "monitor", "notifications", "uptime_kuma"):
        source = {
            p.relative_to(ROOT).as_posix()
            for p in (ROOT / "app" / directory).rglob("*.py")
            if p.stat().st_size
        }
        assert source <= covered, directory


@pytest.mark.parametrize(("week", "area"), [("04", 4), (5, 0), (9, 4), (14, 4), (53, 3), ("01", 1)])
def test_week_number_chooses_the_area_by_last_digit_modulo_five(
    tmp_path: Path, week: int | str, area: int
):
    assert _reads(ROOT, week, tmp_path).returncode == 0

    assert _manifest(tmp_path)[0] == list(AREAS.values())[area]


def test_long_plan_is_split_into_three_parts_of_eight_and_two_halves(tmp_path: Path):
    assert _reads(ROOT, 12, tmp_path).returncode == 0

    parts = _parts(_plan(tmp_path))
    assert [len(part) for part in parts] == [8, 5, 5]
    assert [c for part in parts for c in part] == _commands(_plan(tmp_path))


def test_non_numeric_week_fails_the_step(tmp_path: Path):
    result = _reads(ROOT, "abc", tmp_path)

    assert result.returncode == 1
    assert "Week 'abc' is not a number" in result.stderr


def test_plan_covers_only_the_area_files_and_puts_at_most_eight_in_part_one(
    checkout: Path, tmp_path: Path
):
    result = _reads(checkout, 4, tmp_path)

    assert result.returncode == 0, result.stderr
    plan = _plan(tmp_path)
    files = _manifest(tmp_path)[1]
    assert files == [
        "README.md",
        "docs/user/notifications.md",
        LARGE,
        SMALL,
        "app/uptime_kuma/uptime_kuma_client.py",
        "app/monitor/uptime_kuma_monitor.py",
    ]
    assert "app/notifications/__init__.py" not in plan
    assert "app/tests" not in plan
    assert [len(part) for part in _parts(plan)] == [8]


def test_large_file_is_split_into_joined_600_line_parts(checkout: Path, tmp_path: Path):
    _reads(checkout, 4, tmp_path)

    large = [command for command in _commands(_plan(tmp_path)) if LARGE in command]
    assert large == [HEAD, MIDDLE, TAIL_1201]


def test_missing_mapped_file_fails_the_step(checkout: Path, tmp_path: Path):
    (checkout / "docs/user/notifications.md").unlink()

    result = _reads(checkout, 4, tmp_path)

    assert result.returncode == 1
    assert "File docs/user/notifications.md of focus area" in result.stderr
    assert "READS START" not in (tmp_path / "prompt.txt").read_text(encoding="utf-8")


def test_missing_mapped_directory_fails_the_step(checkout: Path, tmp_path: Path):
    for path in (checkout / "app/uptime_kuma").iterdir():
        path.unlink()
    (checkout / "app/uptime_kuma").rmdir()

    result = _reads(checkout, 4, tmp_path)

    assert result.returncode == 1
    assert "Directory app/uptime_kuma/ of focus area" in result.stderr


@pytest.mark.parametrize("name", ["app/uptime_kuma/a;b.py", "app/uptime_kuma/a b.py"])
def test_unsafe_path_fails_the_step(checkout: Path, tmp_path: Path, name: str):
    _write(checkout, name, "VALUE = 1\n")

    result = _reads(checkout, 4, tmp_path)

    assert result.returncode == 1
    assert "Unsafe path" in result.stderr
    assert "READS START" not in (tmp_path / "prompt.txt").read_text(encoding="utf-8")


def test_part_over_the_cut_fails_the_step(checkout: Path, tmp_path: Path):
    # 700 lines of about 100 bytes: a 600-line part prints about 64,000 characters.
    _write(checkout, LARGE, "".join(f"x_{n:04d} = '{'y' * 90}'\n" for n in range(700)))

    result = _reads(checkout, 4, tmp_path)

    assert result.returncode == 1
    assert "over the 40000-character cut" in result.stderr


def test_missing_prompt_file_fails_the_step(checkout: Path, tmp_path: Path):
    result = subprocess.run(  # noqa: S603
        ["bash", str(READS)],  # noqa: S607 - PATH is fixed to /usr/bin:/bin below
        cwd=checkout,
        env={"PATH": "/usr/bin:/bin", "PROMPT_FILE": str(tmp_path / "none.txt"), "WEEK": "4"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Prompt file" in result.stderr


def _log(work: Path, *calls: tuple[str, str]) -> None:
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
    (work / "agent.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _coverage(
    checkout: Path, work: Path, week: str | None = "4"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(COVERAGE)],  # noqa: S607 - PATH is fixed to /usr/bin:/bin below
        cwd=checkout,
        env={
            "PATH": "/usr/bin:/bin",
            **({"DOCS_DRIFT_WEEK": week} if week is not None else {}),
            "AGENT_LOG": str(work / "agent.log"),
            "AGENT_OUTPUT": str(checkout / "output.json"),
            "GITHUB_STEP_SUMMARY": str(work / "summary.md"),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _items(checkout: Path) -> list[dict]:
    return json.loads((checkout / "output.json").read_text(encoding="utf-8"))["items"]


def _summary(work: Path) -> str:
    return (work / "summary.md").read_text(encoding="utf-8")


ALL_READS = [
    ("cat -n README.md", "success"),
    ("cat -n docs/user/notifications.md", "success"),
    (HEAD, "success"),
    (TAIL_601, "success"),
    (f"cat -n {SMALL}", "success"),
    ("cat -n app/uptime_kuma/uptime_kuma_client.py", "success"),
    ("cat -n app/monitor/uptime_kuma_monitor.py", "success"),
]


@pytest.fixture
def planned(checkout: Path, tmp_path: Path) -> Path:
    assert _reads(checkout, 4, tmp_path).returncode == 0
    return tmp_path


def test_a_run_of_exactly_the_planned_commands_has_full_coverage(checkout: Path, planned: Path):
    calls = [(command, "success") for command in _commands(_plan(planned))]
    _log(planned, *calls)

    result = _coverage(checkout, planned)

    assert result.returncode == 0, result.stderr
    assert "Focus area: Notifications and Uptime Kuma. Read 6 of 6 files" in _summary(planned)
    assert _items(checkout) == [PR]


def test_full_coverage_keeps_the_pull_request(checkout: Path, planned: Path):
    _log(planned, *ALL_READS)

    assert _coverage(checkout, planned).returncode == 0
    assert _items(checkout) == [PR]


def test_skipped_file_fails_and_withholds_the_pull_request(checkout: Path, planned: Path):
    _log(planned, *ALL_READS[:-1])

    result = _coverage(checkout, planned)

    assert result.returncode == 1
    assert "read 5 of 6 files" in result.stderr
    summary = _summary(planned)
    assert "Read 5 of 6 files" in summary
    assert "- app/monitor/uptime_kuma_monitor.py" in summary
    items = _items(checkout)
    assert [item["type"] for item in items] == ["noop"]
    assert items[0]["message"].startswith("INCOMPLETE AUDIT:")


def test_issue_output_is_not_touched_only_pull_requests_are_withheld(checkout: Path, planned: Path):
    other = {"type": "create_issue", "title": "Other", "body": "Other"}
    (checkout / "output.json").write_text(json.dumps({"items": [other, PR]}), encoding="utf-8")
    _log(planned, *ALL_READS[:-1])

    assert _coverage(checkout, planned).returncode == 1
    assert [item["type"] for item in _items(checkout)] == ["create_issue", "noop"]


def test_noop_output_is_left_alone_when_coverage_is_incomplete(checkout: Path, planned: Path):
    noop = {"type": "noop", "message": "NO DRIFT: nothing"}
    (checkout / "output.json").write_text(json.dumps({"items": [noop]}), encoding="utf-8")
    _log(planned)

    assert _coverage(checkout, planned).returncode == 1
    assert _items(checkout) == [noop]


def test_three_parts_that_join_up_count(checkout: Path, planned: Path):
    _log(
        planned,
        *ALL_READS[:2],
        (TAIL_1201, "success"),
        (MIDDLE, "success"),
        (HEAD, "success"),
        *ALL_READS[4:],
    )

    assert _coverage(checkout, planned).returncode == 0


def test_malformed_log_lines_are_skipped(checkout: Path, planned: Path):
    _log(planned, *ALL_READS)
    with (planned / "agent.log").open("a", encoding="utf-8") as log:
        log.write('{\n{"type": "tool_use", "tool_name": "run_shell\n')

    result = _coverage(checkout, planned)

    assert result.returncode == 0, result.stderr
    assert "Read 6 of 6 files" in _summary(planned)


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
def test_reads_that_do_not_count(checkout: Path, planned: Path, calls: list[tuple[str, str]]):
    _log(planned, *[c for c in ALL_READS if LARGE not in c[0]], *calls)

    result = _coverage(checkout, planned)

    assert result.returncode == 1
    assert f"- {LARGE}" in _summary(planned)


def test_missing_log_counts_as_nothing_read(checkout: Path, planned: Path):
    result = _coverage(checkout, planned)

    assert result.returncode == 1
    assert "Read 0 of 6 files" in _summary(planned)


def test_missing_week_fails_the_step(checkout: Path, tmp_path: Path):
    result = _coverage(checkout, tmp_path, week=None)

    assert result.returncode == 1
    assert "DOCS_DRIFT_WEEK is not set" in result.stderr
    assert "the read plan step did not run" in result.stderr


def test_non_numeric_week_fails_the_coverage_step(checkout: Path, tmp_path: Path):
    result = _coverage(checkout, tmp_path, week="abc")

    assert result.returncode == 1
    assert "Week 'abc' is not a number" in result.stderr


def test_the_file_list_comes_from_the_checkout_not_from_anything_written_to_the_job(
    checkout: Path, planned: Path
):
    # Whatever else the agent writes (a shorter plan, a manifest, the prompt), the files that
    # must have been read are rebuilt from the checkout and the week number.
    (planned / "prompt.txt").write_text("ORIGINAL PROMPT\n", encoding="utf-8")
    (planned / "manifest.txt").write_text("AREA Nothing\nREADME.md\n", encoding="utf-8")
    _log(planned, ("cat -n README.md", "success"))

    result = _coverage(checkout, planned)

    assert result.returncode == 1
    assert "Read 1 of 6 files" in _summary(planned)

"""The captcha outcome log outlives the worker: saved before every deploy, never duplicated."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from tests.deployment.test_local_stage1_compose_contract import _repo_text

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "ops" / "captcha-outcomes.sh"
LINE = "INFO thoth_control_plane.acquisition.captcha tiktok captcha outcome"


def _run(tmp_path: Path, worker_log: str) -> str:
    """Run the script against a fake `docker` that prints `worker_log` as the worker's log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp_path / "worker.log").write_text(worker_log, encoding="utf-8")
    fake = bin_dir / "docker"
    fake.write_text(f'#!/usr/bin/env bash\ncat "{tmp_path / "worker.log"}"\n', encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env_file = tmp_path / "stage1.env"
    env_file.write_text(f"THOTH_STAGE1_DATA_ROOT={tmp_path / 'data'}\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(SCRIPT), str(env_file)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        check=True,
    )
    return result.stdout


def _saved(tmp_path: Path) -> list[str]:
    return (tmp_path / "data" / "ops" / "captcha-outcomes.log").read_text().splitlines()


def test_outcomes_are_saved_once_and_survive_a_new_worker(tmp_path: Path) -> None:
    first = (
        f"2026-10-23T10:00:01.5Z {LINE} subtype=whirl solved=true attempts=1 reason=none\n"
        "2026-10-23T10:00:02Z INFO something else entirely\n"
        f"2026-10-23T10:05:00.25Z {LINE} subtype=icon solved=false attempts=1 reason=unsupported\n"
    )
    _run(tmp_path, first)
    _run(tmp_path, first)  # a second save of the same worker log adds nothing
    assert len(_saved(tmp_path)) == 2

    # A deploy recreates the worker: its log starts empty, the saved lines stay.
    report = _run(
        tmp_path,
        f"2026-10-24T08:00:00Z {LINE} subtype=whirl solved=false attempts=2 reason=modal_stayed\n",
    )
    assert len(_saved(tmp_path)) == 3
    assert "3 outcome lines" in report
    assert "subtype=whirl solved=true attempts=1 reason=none" in report
    assert "subtype=icon solved=false attempts=1 reason=unsupported" in report


def test_the_deploy_saves_the_outcomes_before_the_worker_stops() -> None:
    deploy = _repo_text("scripts/ops/deploy-stage1.sh")
    assert deploy.index("captcha-outcomes.sh") < deploy.index("step stop-worker")
    assert "captcha-stats:" in _repo_text("Makefile")

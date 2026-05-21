from __future__ import annotations

import json
import sys

from portal import plot_driver


def test_build_codex_command_includes_expected_flags(tmp_path):
    work_dir = tmp_path / "job"
    output_last_message = work_dir / "codex-last-message.md"

    command = plot_driver.build_codex_command(work_dir, output_last_message)

    assert command == [
        "codex",
        "exec",
        "--cd",
        str(work_dir),
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--dangerously-bypass-approvals-and-sandbox",
        "--output-last-message",
        str(output_last_message),
    ]


def test_codex_executor_requires_runtime_api_key(tmp_path, monkeypatch):
    work_dir = tmp_path / "job"
    work_dir.mkdir()
    prompt_path = work_dir / "prompt.txt"
    context_path = work_dir / "context.json"
    prompt_path.write_text("make a plot", encoding="utf-8")
    context_path.write_text(
        json.dumps({"backend_profile": "rdf", "resolved_dataset": ""}),
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PLOT_DRIVER_EXECUTOR", "codex")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plot_driver",
            "--job-id",
            "job-1",
            "--work-dir",
            str(work_dir),
            "--prompt-path",
            str(prompt_path),
            "--context-path",
            str(context_path),
        ],
    )

    exit_code = plot_driver.main()

    assert exit_code == 3
    assert "OPENAI_API_KEY is required" in (work_dir / "run.log").read_text(
        encoding="utf-8"
    )

from __future__ import annotations

import json
import subprocess
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


class _SecretProvider:
    def has_secret(self, name: str) -> bool:
        return name == "OPENAI_API_KEY"

    def get_secret(self, name: str) -> str:
        if name != "OPENAI_API_KEY":
            raise AssertionError(name)
        return "secret-from-file"

    def materialize_secret_file(self, name, destination):
        raise NotImplementedError


def test_codex_executor_uses_secret_provider_when_env_is_missing(tmp_path, monkeypatch):
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
    monkeypatch.setattr(plot_driver, "get_secret_provider", lambda: _SecretProvider())
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

    calls = []

    def fake_run(command, cwd, env, capture_output, text, input=None, check=False):
        calls.append((command, cwd, env, input))
        if command[:2] == ["codex", "exec"]:
            (work_dir / "generated.py").write_text("print('hi')\n", encoding="utf-8")
            (work_dir / "comments.md").write_text("notes\n", encoding="utf-8")
            (work_dir / "plot.svg").write_text("<svg />\n", encoding="utf-8")
            (work_dir / "run.log").write_text("codex ok\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="codex ok\n", stderr="")
        if command[:2] == ["uv", "run"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv ok\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(plot_driver.subprocess, "run", fake_run)

    exit_code = plot_driver.main()

    assert exit_code == 0
    assert calls[0][2]["OPENAI_API_KEY"] == "secret-from-file"


def test_codex_executor_bootstraps_codex_home(tmp_path, monkeypatch):
    work_dir = tmp_path / "job"
    codex_home = tmp_path / "codex-home"
    work_dir.mkdir()
    prompt_path = work_dir / "prompt.txt"
    context_path = work_dir / "context.json"
    prompt_path.write_text("make a plot", encoding="utf-8")
    context_path.write_text(
        json.dumps({"backend_profile": "rdf", "resolved_dataset": ""}),
        encoding="utf-8",
    )

    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")
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

    def fake_run(command, cwd, env, capture_output, text, input=None, check=False):
        if command[:2] == ["codex", "exec"]:
            (work_dir / "generated.py").write_text("print('hi')\n", encoding="utf-8")
            (work_dir / "comments.md").write_text("notes\n", encoding="utf-8")
            (work_dir / "plot.svg").write_text("<svg />\n", encoding="utf-8")
            (work_dir / "run.log").write_text("codex ok\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="codex ok\n", stderr="")
        if command[:2] == ["uv", "run"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv ok\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(plot_driver.subprocess, "run", fake_run)

    exit_code = plot_driver.main()

    assert exit_code == 0
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == (
        'model = "gpt-5.4-mini"\n'
        'model_reasoning_effort = "medium"\n'
        '[projects."/app"]\n'
        'trust_level = "trusted"\n'
    )
    assert json.loads((codex_home / "auth.json").read_text(encoding="utf-8")) == {
        "OPENAI_API_KEY": "sk-test-value",
        "auth_mode": "apikey",
    }

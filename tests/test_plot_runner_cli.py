from __future__ import annotations

import sys
from unittest import mock

from portal import plot_runner_cli


def test_plot_runner_cli_forwards_run_command(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plot-runner",
            "run",
            "--job-id",
            "job-123",
            "--fail",
        ],
    )

    with mock.patch("portal.plot_runner_cli.os.execvp") as execvp:
        plot_runner_cli.main()

    execvp.assert_called_once_with(
        sys.executable,
        [
            sys.executable,
            "manage.py",
            "plot_runner",
            "--job-id",
            "job-123",
            "--fail",
        ],
    )

from __future__ import annotations

import argparse
import os
import sys


def build_manage_command(job_id: str, *, fail: bool = False) -> list[str]:
    command = [
        sys.executable,
        "manage.py",
        "plot_runner",
        "--job-id",
        job_id,
    ]
    if fail:
        command.append("--fail")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plot-runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one plot job")
    run_parser.add_argument("--job-id", required=True)
    run_parser.add_argument("--fail", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "run":
        os.execvp(
            sys.executable,
            build_manage_command(args.job_id, fail=args.fail),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

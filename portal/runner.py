from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic

from django.conf import settings

from portal.artifacts import ArtifactRef, get_artifact_store
from portal.models import ArtifactKind, Job, JobArtifact
from portal.secrets import get_secret_provider, redact_secret_values
from portal.services import claim_job, mark_completed, mark_failed


@dataclass(frozen=True, slots=True)
class RunnerResult:
    job: Job
    artifact_refs: tuple[ArtifactRef, ...]
    work_dir: Path
    prompt_path: Path
    context_path: Path


@dataclass(frozen=True, slots=True)
class PlotRunnerContext:
    job_id: str
    submission_id: str
    original_prompt: str
    backend_profile: str
    resolved_dataset: str
    database_url: str
    artifact_storage_backend: str
    blob_container: str
    queue_backend: str
    queue_name: str
    queue_visibility_timeout_seconds: int
    plot_runner_timeout_seconds: int
    secret_source: str
    servicex_config_path: str
    servicex_config_present: bool
    openai_api_key_present: bool
    github_client_id_present: bool
    github_client_secret_present: bool
    key_vault_url: str
    key_vault_name: str


@dataclass(frozen=True, slots=True)
class PlotDriverResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def build_codex_prompt(job: Job) -> str:
    return (
        "$iris-hep Please write a stand-alone python file that we can use uv to run "
        "(and auto install) that will do the following. It should produce a plot and "
        f"a file comments.md with comments as output: {job.original_prompt}"
    )


def _runner_root() -> Path:
    root = Path(settings.PLOT_RUNNER_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def prepare_runner_work_dir(job_id: str) -> Path:
    work_dir = _runner_root() / job_id
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def build_plot_runner_context(job: Job) -> PlotRunnerContext:
    database_url = getattr(settings, "DATABASE_URL", None) or ""
    servicex_path = Path(settings.SERVICEX_CONFIG_PATH)
    secret_provider = get_secret_provider()
    return PlotRunnerContext(
        job_id=str(job.submission_id),
        submission_id=str(job.submission_id),
        original_prompt=job.original_prompt,
        backend_profile=job.backend_profile,
        resolved_dataset=job.resolved_dataset,
        database_url=database_url,
        artifact_storage_backend=settings.ARTIFACT_STORAGE_BACKEND,
        blob_container=settings.BLOB_CONTAINER_NAME,
        queue_backend=settings.QUEUE_BACKEND,
        queue_name=settings.QUEUE_NAME,
        queue_visibility_timeout_seconds=settings.QUEUE_VISIBILITY_TIMEOUT_SECONDS,
        plot_runner_timeout_seconds=settings.PLOT_RUNNER_TIMEOUT_SECONDS,
        secret_source=settings.SECRET_SOURCE,
        servicex_config_path=str(servicex_path),
        servicex_config_present=servicex_path.exists()
        or secret_provider.has_secret("SERVICEX_CONFIG_PATH"),
        openai_api_key_present=secret_provider.has_secret("OPENAI_API_KEY"),
        github_client_id_present=secret_provider.has_secret("GITHUB_CLIENT_ID"),
        github_client_secret_present=secret_provider.has_secret("GITHUB_CLIENT_SECRET"),
        key_vault_url=settings.KEY_VAULT_URL or "",
        key_vault_name=settings.KEY_VAULT_NAME or "",
    )


def _write_runner_inputs(
    work_dir: Path,
    job: Job,
    context: PlotRunnerContext,
) -> tuple[Path, Path]:
    secret_provider = get_secret_provider()
    prompt_path = work_dir / "prompt.txt"
    context_path = work_dir / "context.json"
    job_path = work_dir / "job.json"
    secrets_dir = work_dir / "secrets"
    prompt_path.write_text(build_codex_prompt(job), encoding="utf-8")
    context_path.write_text(
        json.dumps(asdict(context), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    job_path.write_text(
        json.dumps(
            {
                "backend_profile": job.backend_profile,
                "job_id": str(job.submission_id),
                "original_prompt": job.original_prompt,
                "resolved_dataset": job.resolved_dataset,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    servicex_source = Path(context.servicex_config_path)
    if servicex_source.exists():
        secrets_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(servicex_source, secrets_dir / "servicex.yaml")
    elif secret_provider.has_secret("SERVICEX_CONFIG_PATH"):
        secrets_dir.mkdir(parents=True, exist_ok=True)
        secret_provider.materialize_secret_file(
            "SERVICEX_CONFIG_PATH",
            secrets_dir / "servicex.yaml",
        )
    return prompt_path, context_path


def _write_known_artifacts(job: Job, work_dir: Path) -> tuple[ArtifactRef, ...]:
    refs: list[ArtifactRef] = []
    for artifact_kind, filename, content_type in [
        (ArtifactKind.SCRIPT, "generated.py", "text/x-python"),
        (ArtifactKind.REPORT, "comments.md", "text/markdown"),
        (ArtifactKind.PLOT, "plot.svg", "image/svg+xml"),
        (ArtifactKind.LOG, "run.log", "text/plain"),
    ]:
        path = work_dir / filename
        if not path.exists():
            continue
        refs.append(
            _artifact_store().put_artifact(
                job_id=str(job.submission_id),
                local_path=path,
                artifact_kind=artifact_kind,
                content_type=content_type,
                is_canonical=True,
            )
        )
    for ref in refs:
        _record_artifact(job, ref)
    return tuple(refs)


def _append_run_log(work_dir: Path, content: str) -> None:
    log_path = work_dir / "run.log"
    previous = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    _write_text(log_path, previous + content)


def build_plot_driver_command(
    job: Job,
    work_dir: Path,
    prompt_path: Path,
    context_path: Path,
) -> list[str]:
    driver = getattr(settings, "PLOT_RUNNER_DRIVER", "python -m portal.plot_driver")
    command = shlex.split(driver) if isinstance(driver, str) else list(driver)
    return [
        *command,
        "--job-id",
        str(job.submission_id),
        "--work-dir",
        str(work_dir),
        "--prompt-path",
        str(prompt_path),
        "--context-path",
        str(context_path),
    ]


def run_plot_driver_subprocess(
    job: Job,
    work_dir: Path,
    prompt_path: Path,
    context_path: Path,
    *,
    timeout_seconds: int,
    fail: bool = False,
) -> PlotDriverResult:
    command = build_plot_driver_command(job, work_dir, prompt_path, context_path)
    env = os.environ.copy()
    if fail:
        env["PLOT_DRIVER_FAIL"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=Path(settings.BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _append_run_log(
            work_dir,
            "".join(
                [
                    (exc.stdout or ""),
                    (exc.stderr or ""),
                    f"timeout after {timeout_seconds}s\n",
                ]
            ),
        )
        return PlotDriverResult(
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            timed_out=True,
        )

    _append_run_log(
        work_dir,
        "".join(
            [
                completed.stdout or "",
                completed.stderr or "",
                f"exit code {completed.returncode}\n",
            ]
        ),
    )
    return PlotDriverResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _runner_secret_values() -> list[str]:
    secret_provider = get_secret_provider()
    secret_values: list[str] = []
    for name in ("OPENAI_API_KEY", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"):
        if secret_provider.has_secret(name):
            try:
                secret_values.append(secret_provider.get_secret(name))
            except Exception:  # pragma: no cover - defensive redaction helper
                continue
    return secret_values


def _artifact_store():
    return get_artifact_store()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _record_artifact(job: Job, ref: ArtifactRef) -> JobArtifact:
    return JobArtifact.objects.create(
        job=job,
        artifact_kind=ref.artifact_kind,
        blob_container=ref.blob_container,
        blob_key=ref.blob_key,
        content_type=ref.content_type,
        size_bytes=ref.size_bytes,
        is_canonical=ref.is_canonical,
    )


def _fake_generated_script(job: Job) -> str:
    return "\n".join(
        [
            "# Generated by the fake local plot runner.",
            f"# Submission: {job.submission_id}",
            f"# Prompt: {job.original_prompt}",
            "",
            "print('hello from the fake plot runner')",
        ]
    )


def _fake_comments(job: Job) -> str:
    return "\n".join(
        [
            f"# Comments for {job.submission_id}",
            "",
            job.original_prompt,
        ]
    )


def _fake_svg(job: Job) -> str:
    return "\n".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="320">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<text x="24" y="48" font-size="24" fill="black">Fake plot</text>',
            f'<text x="24" y="88" font-size="16" fill="black">{job.backend_profile}</text>',
            f'<text x="24" y="120" font-size="16" fill="black">{job.submission_id}</text>',
            "</svg>",
        ]
    )


def run_fake_plot_job(job_id: str, *, fail: bool = False) -> RunnerResult:
    job = claim_job(job_id)
    started = monotonic()
    refs: list[ArtifactRef] = []
    work_dir = prepare_runner_work_dir(str(job.submission_id))
    context = build_plot_runner_context(job)
    prompt_path, context_path = _write_runner_inputs(work_dir, job, context)

    try:
        script_path = work_dir / "generated.py"
        comments_path = work_dir / "comments.md"
        plot_path = work_dir / "plot.svg"
        log_path = work_dir / "run.log"

        _write_text(script_path, _fake_generated_script(job))
        _write_text(comments_path, _fake_comments(job))
        _write_text(log_path, f"runner started for {job.submission_id}\n")

        if fail:
            _write_text(log_path, log_path.read_text(encoding="utf-8") + "simulated failure\n")
            refs.extend(_write_known_artifacts(job, work_dir))
            job = mark_failed(job, failure_message="Simulated plot runner failure")
            return RunnerResult(
                job=job,
                artifact_refs=tuple(refs),
                work_dir=work_dir,
                prompt_path=prompt_path,
                context_path=context_path,
            )

        _write_text(plot_path, _fake_svg(job))
        _write_text(log_path, log_path.read_text(encoding="utf-8") + "simulated success\n")
        refs.extend(_write_known_artifacts(job, work_dir))

        elapsed = monotonic() - started
        job = mark_completed(
            job,
            result_metadata={
                "artifacts": [ref.blob_key for ref in refs],
                "runtime_seconds": round(elapsed, 3),
            },
        )
        Job.objects.filter(pk=job.pk).update(runtime_seconds=elapsed)
        return RunnerResult(
            job=job,
            artifact_refs=tuple(refs),
            work_dir=work_dir,
            prompt_path=prompt_path,
            context_path=context_path,
        )
    except Exception as exc:
        job = mark_failed(
            job,
            failure_message=redact_secret_values(
                f"Runner crashed: {exc}",
                _runner_secret_values(),
            ),
        )
        return RunnerResult(
            job=job,
            artifact_refs=tuple(refs),
            work_dir=work_dir,
            prompt_path=prompt_path,
            context_path=context_path,
        )


def run_command_plot_job(job_id: str, *, fail: bool = False) -> RunnerResult:
    job = claim_job(job_id)
    started = monotonic()
    refs: list[ArtifactRef] = []
    work_dir = prepare_runner_work_dir(str(job.submission_id))
    context = build_plot_runner_context(job)
    prompt_path, context_path = _write_runner_inputs(work_dir, job, context)

    try:
        result = run_plot_driver_subprocess(
            job,
            work_dir,
            prompt_path,
            context_path,
            timeout_seconds=context.plot_runner_timeout_seconds,
            fail=fail,
        )
        refs.extend(_write_known_artifacts(job, work_dir))
        if result.timed_out:
            job = mark_failed(
                job,
                failure_message=(
                    f"Plot runner timed out after {context.plot_runner_timeout_seconds}s"
                ),
            )
        elif result.returncode != 0:
            job = mark_failed(
                job,
                failure_message=f"Plot runner exited with code {result.returncode}",
            )
        else:
            elapsed = monotonic() - started
            job = mark_completed(
                job,
                result_metadata={
                    "artifacts": [ref.blob_key for ref in refs],
                    "runtime_seconds": round(elapsed, 3),
                },
            )
            Job.objects.filter(pk=job.pk).update(runtime_seconds=elapsed)
        return RunnerResult(
            job=job,
            artifact_refs=tuple(refs),
            work_dir=work_dir,
            prompt_path=prompt_path,
            context_path=context_path,
        )
    except Exception as exc:
        job = mark_failed(
            job,
            failure_message=redact_secret_values(
                f"Runner crashed: {exc}",
                _runner_secret_values(),
            ),
        )
        return RunnerResult(
            job=job,
            artifact_refs=tuple(refs),
            work_dir=work_dir,
            prompt_path=prompt_path,
            context_path=context_path,
        )

# Agent Guidance

This repository is building the low-cost cloud-native plot portal described in `docs/2026-05-21-v1-spec.md`. Use `docs/2026-05-21-v1-implementation-plan.md` as the execution checklist.

## Source Of Truth

- Read the spec before changing architecture.
- Read the implementation plan before implementing a checklist item.
- Preserve the user-facing flow from `hep-data-web`, but do not copy its old execution architecture.
- Keep checklist state honest: only mark an item complete after code, tests, and docs for that item are done.

## Architecture Rules

- The Django web app must not run plot jobs inside HTTP requests.
- The web app must not require Docker socket access.
- Queue messages must contain only minimal routing data: job id and backend profile.
- The database job row is the durable source of truth. Queue messages are delivery hints.
- Store generated files in blob/object storage. Store only metadata, preview text, status, and failure summaries in the database.
- Keep SDK-specific code behind adapter interfaces: `QueueClient`, `ArtifactStore`, `SecretProvider`, `JobStore`, and `PlotExecutor`.
- Keep local development close to production by using Postgres and Azurite for integration flows.
- Production relational storage is Azure SQL for cost reasons. Test SQL Server/Azure SQL compatibility instead of assuming PostgreSQL-only behavior.
- Production plot execution should use queue-triggered Azure Container Apps Jobs.
- Enforce single-active-job behavior in the service/database layer, not only through queue or container settings.
- Generated source code is a blob artifact only. Do not store it in the database; load it asynchronously on the job detail page after the main page renders.
- V1 only needs queued-job cancellation. Running-job cancellation is deferred, but Codex/script execution must have a configurable timeout, initially 10 minutes, that kills overlong execution and uploads available partial artifacts/logs.
- Keep the real plot-runner Dockerfile/image in this repo because it must include Codex and this repo's runner contract.
- Never place secrets in git, queue messages, images, job metadata, or logs.

## Implementation Style

- Work one narrow checklist item or tightly related group at a time.
- Add or update tests with each behavior change.
- Prefer small service functions over embedding business logic in views, templates, or management commands.
- Use fakes for fast unit tests and Azurite/Postgres for integration tests.
- Keep frontend behavior close to the previous app's routes and templates unless the plan explicitly changes it.
- When a decision is still open in the plan, use the chosen default unless the user has answered differently.

## Verification Expectations

- Run the strongest practical test command for the changed area.
- For Django model/service/view work, include targeted tests before broad smoke tests.
- For adapter work, test both fake behavior and the Azurite/Azure boundary where practical.
- For Docker Compose changes, run `docker compose config` before asking others to try the stack.
- If a test cannot run because credentials, Docker, Azure, or network are unavailable, document the exact blocker and the narrower verification that did run.

## Common Pitfalls

- Do not reintroduce the old database-claimed worker as the production design.
- Do not make the web app start local Docker containers except behind the local runner/development path.
- Do not put prompt text, generated code, ServiceX config, tokens, or OpenAI keys in queue payloads.
- Do not delete queue messages before terminal job state is durably recorded.
- Do not let templates or views depend directly on Azure SDK objects.
- Do not make every test require Docker or real Azure.

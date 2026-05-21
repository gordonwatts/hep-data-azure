# V1 Implementation Plan

Source spec: `docs/2026-05-21-v1-spec.md`

## Summary

Build a low-cost Django plot portal that preserves the user-facing flow from `hep-data-web` while replacing its local database-claimed worker and filesystem artifacts with a queue/blob/runner architecture. The web app stays always on and cheap; analysis runs in isolated plot-runner jobs only when work exists.

The first usable milestone is a local Docker Compose stack where an approved user can submit a plot request, the web app writes a durable job row and Azure Storage Queue message, a local runner consumes the message, a fake plot executor records blob-backed artifacts, and the job detail page displays the result. Later milestones replace fakes with the real plot-runner container, add Azure adapters, and verify an Azure end-to-end smoke test.

## Chosen Defaults

- Use Django for the web app, following the prior `hep-data-web` project/app/template shape where practical.
- Use Azure SQL for production relational storage to keep managed database cost lower. Use local SQL Server/Azure SQL-compatible development where practical, or keep PostgreSQL only as a temporary local convenience until SQL Server compatibility is tested.
- Use Azure Storage Queue and Azure Blob Storage as first-class interfaces from the start. Local development uses Azurite rather than a filesystem artifact store, except for unit-test fakes.
- Store generated code only as a `script` blob artifact with metadata in `JobArtifact`. The job detail page may display source code, but it must fetch the script asynchronously after the main page loads.
- Store plot outputs, reports, logs, bundles, and generated scripts as blob artifacts with metadata in `JobArtifact`.
- Keep queue messages minimal: `{"job_id": "<uuid>", "backend_profile": "<profile>"}`. Never include prompts, generated code, secrets, or user data in queue messages.
- Enforce single-active-job behavior in the database/service layer before relying on queue visibility or container job concurrency.
- Implement queued-job cancellation first. Running-job cancellation can be deferred until the real plot runner has safe checkpoints.
- Add a configurable Codex/script execution timeout, defaulting initially to 10 minutes. On timeout, kill the execution, upload any generated partial artifacts/logs that are available, and mark the job failed with a timeout message.
- Use queue-triggered Azure Container Apps Jobs for production plot execution. The web app writes the database row and queue message, then Azure starts plot jobs from queue pressure rather than requiring the web app to orchestrate job starts.
- Keep the real plot-runner Dockerfile/image definition in this repo. It can borrow package/install ideas from `hep-data-llm`, but it must include Codex, the `iris-hep/marketplace` skills, and this repo's `plot-runner run --job-id` contract.
- Treat the previous `hep-data-web` repository as behavior reference only. Do not copy its old direct subprocess execution, Docker socket access from Django, local worker, or filesystem artifact path model.

## Public Interfaces / Core Concepts

### Django Routes

Preserve these route concepts from the spec and previous app:

- `/` and `/submit/`: home and plot submission.
- `/jobs/<submission_id>/`: job detail.
- `/jobs/<submission_id>/status/`: polling partial.
- `/jobs/<submission_id>/clone/`: clone/edit/resubmit.
- `/jobs/<submission_id>/artifacts/<artifact_id>/`: authorized artifact inline/download.
- Auth routes: login, logout, account status.
- Admin routes: user approvals, admin job list, queued-job cancellation.

### Models

- `UserProfile`: approval state, approver/rejecter audit fields, rejection reason.
- `Job`: UUID/submission id, owner, prompt, resolved dataset, backend profile, status, queue metadata, timestamps, retry count, failure message, result metadata.
- `JobArtifact`: job, artifact kind, blob container/key, content type, size, canonical flag, created timestamp.

### Service Boundaries

Keep these boundaries small and testable:

- `QueueClient`: enqueue, receive, delete, abandon.
- `ArtifactStore`: put artifact, get read URL, delete artifacts for job.
- `SecretProvider`: string secrets and file-style secrets.
- `JobStore`: transactional job creation, claim, status transitions, cancellation, ownership checks.
- `PlotExecutor`: local runner invokes plot-runner; production plot execution is handled by queue-triggered Azure Container Apps Jobs.

### Commands / Processes

- `manage.py runserver`: local web development.
- `manage.py run_local_job_runner`: polls the local queue and processes one message at a time.
- `plot-runner run --job-id <uuid>`: plot-runner contract. It loads job context from configured services, writes artifacts, and updates job status.
- `docker compose up`: starts web, postgres, azurite, local-job-runner, and optionally plot-runner.

### Configuration

Use environment variables for settings and paths. Expected groups:

- Django: secret key, allowed hosts, debug, database URL.
- Storage: account name/key or connection string, queue name, blob container, Azurite endpoints.
- Runner: max runtime, Codex/script execution timeout, visibility timeout, poll interval, plot-runner image/command.
- Auth: GitHub OAuth client id/secret or local stub controls.
- Secrets: local `servicex.yaml` path, OpenAI API key source, Key Vault name/URI for Azure.

## Implementation Checklist

### 1. Repository Foundation

- [ ] Create the Django project skeleton with app modules matching the previous app shape: project package, `portal` app, settings split, URLs, templates directory, static directory, and `manage.py`.
- [ ] Add Python packaging and tooling files with explicit dev commands for tests, linting, formatting, and Django management commands.
- [ ] Add a minimal README that explains local setup, required secret files, and the intended `docker compose up` workflow.
- [ ] Add `.gitignore` entries for virtualenvs, local databases, `.env`, secret files, generated artifacts, test caches, and coverage output.
- [ ] Add baseline CI that installs dependencies and runs the fastest reliable test command.
- [ ] Verification: run the empty Django smoke test or `manage.py check` plus the configured test command.

Connection to watch: do not start by implementing runner logic inside Django views. The foundation should make room for service modules and adapters before job execution exists.

### 2. Settings And Configuration

- [ ] Implement `base`, `dev`, `test`, and `prod` settings modules.
- [ ] Configure Azure SQL/SQL Server through `DATABASE_URL` or equivalent env settings, with SQLite allowed only for narrow tests if it does not hide SQL Server compatibility behavior.
- [ ] Add storage settings for queue/blob names, Azurite endpoints, and production Azure connection options.
- [ ] Add polling interval settings and make the browser value seconds-based in Python but milliseconds-based in JavaScript.
- [ ] Add secret-source settings for local files and future Key Vault use.
- [ ] Verification: add settings tests that load test settings and assert required defaults are present without reading real secrets.

Connection to watch: local and production should use the same service interfaces. Avoid scattering raw environment reads through views, models, runner code, or templates.

### 3. Models And Migrations

- [ ] Add `JobStatus`, `ArtifactKind`, `ApprovalState`, and user role/status concepts as explicit choices.
- [ ] Add `UserProfile` with approval state and audit fields: approved/rejected timestamps, actor fields, and optional rejection reason.
- [ ] Add `Job` with UUID/submission id, owner, original prompt, resolved dataset, backend profile, status, queue message id, retry count, timestamps, timeout metadata, failure message, queue position/depth fields, and JSON result metadata.
- [ ] Add `JobArtifact` with artifact kind, blob container, blob key, content type, size, canonical flag, and timestamp.
- [ ] Add indexes for owner/status, submission id, status timestamps, and job artifacts by job/kind.
- [ ] Add constraints or service-enforced checks for valid terminal/running status transitions where practical.
- [ ] Verification: model tests for defaults, string representations if used in admin/UI, artifact metadata, and migration generation.

Connection to watch: queue message id is metadata, not the source of truth. The job row must remain the durable state for web display and runner decisions.

### 4. Backend Profiles And Prompt Helpers

- [ ] Implement backend profile definitions for `servicex_awkward` and `rdf` with labels and any existing dataset inference behavior from the previous app.
- [ ] Implement prompt/dataset merge helpers for form submission and clone/resubmit.
- [ ] Add example-prompt loading if examples are part of the first UI milestone.
- [ ] Keep profile names stable because queue messages and runner behavior depend on them.
- [ ] Verification: tests for profile listing, default profile, dataset inference, and prompt merge behavior.

Connection to watch: the backend profile selected in the web form must be the same value stored on `Job`, sent in the queue message, and understood by the plot runner.

### 5. Queue Client Interface

- [ ] Define a `QueueClient` protocol or small class interface with `enqueue_job`, `receive_messages`, `delete_message`, and `abandon_message`.
- [ ] Implement an in-memory fake for unit tests.
- [ ] Implement Azure Storage Queue support that works against Azurite locally.
- [ ] Ensure `enqueue_job` serializes only `job_id` and `backend_profile`.
- [ ] Record returned message id on the `Job` when available.
- [ ] Add queue visibility timeout and poison/retry behavior settings.
- [ ] Verification: unit tests for fake client, message shape, missing/invalid message payloads, and Azurite-backed behavior if practical in integration tests.

Connection to watch: do not put prompts or secrets into queue payloads. The runner must load all sensitive and large context from the database, blob storage, or secret provider.

### 6. Artifact Store Interface

- [ ] Define `ArtifactRef` and an `ArtifactStore` interface with `put_artifact`, `get_read_url`, and `delete_artifacts_for_job`.
- [ ] Implement an in-memory or temp-directory fake for unit tests.
- [ ] Implement Azure Blob Storage support that works against Azurite locally.
- [ ] Standardize blob keys, for example `jobs/<job_id>/<artifact_kind>/<filename>`.
- [ ] Normalize content-type detection and explicit artifact kinds: `report`, `plot`, `script`, `log`, `bundle`.
- [ ] Ensure read URLs are short-lived or proxied through authorized Django views.
- [ ] Verification: tests for upload metadata, generated read URL/proxy behavior, content type, size, canonical artifact selection, and deletion.

Connection to watch: `JobArtifact` stores blob metadata only. Do not reintroduce filesystem paths into the model as a production concept.

### 7. Job Store And Status Transitions

- [ ] Implement service functions for `create_queued_job`, `claim_job`, `mark_running`, `mark_completed`, `mark_failed`, `mark_cancelled`, and user/admin job listing.
- [ ] Make job creation transactional: create the row, enqueue the message, record queue metadata, and leave a clear failure path if enqueue fails.
- [ ] Enforce owner-only visibility for regular users and all-job visibility for staff/admins.
- [ ] Enforce single-active-job behavior before marking a job running.
- [ ] Define how stale `running` jobs are detected or timed out.
- [ ] Verification: unit tests for legal and illegal status transitions, user isolation, admin access, single-active-job enforcement, enqueue failure behavior, and cancellation of queued jobs.

Connection to watch: queue delivery can repeat. `claim_job` and terminal-state checks must be idempotent enough that duplicate messages do not create duplicate executions or corrupt terminal jobs.

### 8. Authentication And Approval Flow

- [ ] Add GitHub OAuth integration or a development authentication stub that can later be replaced without changing approval logic.
- [ ] Add middleware or view checks so pending/rejected users cannot submit jobs.
- [ ] Add admin approval/rejection views with audit fields.
- [ ] Add account status, login, and logout routes/templates.
- [ ] Add local test helpers for approved user, pending user, rejected user, and admin.
- [ ] Verification: tests for first sign-in pending state, approved access, rejected access, admin approve/reject, and session behavior after approval refresh.

Connection to watch: do not block admin approval pages behind the same pending-user guard that pending users hit. Staff/admin flow needs a clear bypass.

### 9. Web Submission And History UI

- [ ] Build home/submit form for prompt, backend profile, optional dataset, and example prompts.
- [ ] On valid submission, create a queued job through `JobStore` and `QueueClient`, then redirect to job detail.
- [ ] Add history table for the current user and admin job list for staff/admins.
- [ ] Add clone/resubmit flow that preserves the original prompt/profile/dataset while creating a new job on submit.
- [ ] Surface queue position/depth if available without making it a correctness dependency.
- [ ] Verification: tests for submit success, validation errors, queue message creation, history visibility, clone/resubmit, and forbidden cross-user access.

Connection to watch: views should call services, not queue or blob SDKs directly. This keeps Azure/local differences out of the templates and view logic.

### 10. Job Detail, Polling, And Artifact Views

- [ ] Build job detail view showing prompt, resolved dataset, backend profile, status, timing, failure message, plot previews, report links, and logs when available.
- [ ] Add an authorized generated-code endpoint or artifact fetch path so the job detail page can load source code asynchronously after the main page renders.
- [ ] Build the polling partial at `/jobs/<submission_id>/status/` and poll only while status is `queued` or `running`.
- [ ] Keep polling configurable: 1-2 seconds locally, 3-5 seconds in production if needed.
- [ ] Implement artifact inline/download views with ownership/admin authorization.
- [ ] Use `ArtifactStore.get_read_url` or a proxy response, but keep authorization in Django before exposing blob content.
- [ ] Verification: tests for status partial rendering, polling stops on terminal statuses, generated-code display, failure-message rendering, artifact authorization, and content disposition for inline/download.

Connection to watch: artifact routes should keep the previous URL semantics even though storage is blob-backed. Templates should not need to know whether the blob is Azurite or Azure.

### 11. Fake Plot Runner Milestone

- [ ] Add `plot-runner run --job-id <uuid>` command entry point or management command wrapper using the same service boundaries planned for the real runner.
- [ ] Implement a fake executor mode that marks the job running, writes a tiny plot placeholder, `comments.md`, generated script, and log artifact, then marks completed.
- [ ] Implement fake failure mode for testing that marks failed with a clear failure message and log artifact.
- [ ] Ensure the runner refuses missing, terminal, cancelled, or already-running jobs safely.
- [ ] Verification: integration tests for fake success, fake failure, duplicate message handling, artifact records, script artifact creation, asynchronous source-code loading, and terminal status updates.

Connection to watch: this is not throwaway if structured correctly. The fake executor should exercise the same `JobStore`, `ArtifactStore`, and `SecretProvider` seams as the real runner.

### 12. Local Job Runner Process

- [ ] Add `run_local_job_runner` command that polls one queue message at a time.
- [ ] For each message, validate payload, skip/discard missing or terminal jobs, invoke the plot-runner command/container, and delete the message only after durable terminal state is known.
- [ ] Abandon or leave messages visible again when processing fails before durable state is known.
- [ ] Respect poll interval, max messages of 1, visibility timeout, retry count, and stop-after-one options for tests.
- [ ] Verification: tests for successful consume/delete, missing job discard, terminal job discard, runner failure retry, invalid payload handling, and single-message processing.

Connection to watch: the local runner simulates the production trigger path. It should not become a second implementation of plot execution business logic.

### 13. Docker Compose Local Stack

- [ ] Add Dockerfiles for web/local runner and a repo-owned plot-runner image or command container.
- [ ] Add `docker-compose.yml` with `web`, `postgres`, `azurite`, `local-job-runner`, and optional `plot-runner`.
- [ ] Add a migration/init path so the app starts against an empty database.
- [ ] Mount local secret files such as `./secrets/servicex.yaml` without committing them.
- [ ] Configure web and runner to share Postgres and Azurite endpoints.
- [ ] Verification: `docker compose config`, app startup, migrations, submit job, local runner completes fake job, artifacts survive container restart.

Connection to watch: the web container must not require Docker socket access. Only the local runner or test harness may invoke a plot-runner container locally.

### 14. Integration Test Harness

- [ ] Add tests that exercise submit -> queue -> local runner -> fake plot runner -> blob artifact -> web result.
- [ ] Add tests for cross-user artifact/job access denial.
- [ ] Add failed-job tests that verify failure text and logs appear.
- [ ] Add restart/persistence test instructions or automated Compose smoke where practical.
- [ ] Add fixtures/factories for users, approvals, jobs, queue messages, and artifacts.
- [ ] Verification: document and run targeted integration test commands in CI or local developer docs.

Connection to watch: use fakes for fast unit tests and Azurite/Postgres for integration tests. Do not make every test require Docker or real Azure.

### 15. Real Plot Runner Contract

- [ ] Implement the real plot-runner command with `plot-runner run --job-id <uuid>`.
- [ ] Load job prompt, backend profile, dataset, database, storage, and secret config from services/settings.
- [ ] Create an isolated working directory per job.
- [ ] Build the Codex prompt exactly from the spec pattern: `$iris-hep Please write a stand-alone python file that we can use uv to run (and auto install) that will do the following. It should produce a plot and a file comments.md with comments as output: <plot-question>`.
- [ ] Install or include the `iris-hep/marketplace` skills in the plot-runner image.
- [ ] Define the real plot-runner Dockerfile in this repo, including Codex installation/configuration plus the analysis dependencies needed for ROOT/Python/ServiceX workflows.
- [ ] Run Codex with an OpenAI API key supplied at runtime, not baked into the image.
- [ ] Enforce a configurable Codex/script execution timeout, defaulting to 10 minutes for initial implementation.
- [ ] On timeout, kill the active execution, upload any generated code, `comments.md`, plots, logs, or partial outputs that exist, and mark the job failed with a clear timeout message.
- [ ] Capture generated code, `comments.md`, terminal log, plots, and bundles as artifacts.
- [ ] Catch crashes and mark failed with sanitized exception summaries and log artifacts.
- [ ] Verification: unit tests around command construction/sanitization, fake subprocess tests for success/failure/timeout, partial artifact upload on timeout, and one local real-run smoke test when credentials and ServiceX config are available.

Connection to watch: the spec says outputs should be saved back to the database, but the architecture says large files belong in blob storage. Implement this as DB metadata plus failure text in DB, with generated code and other outputs as blob artifacts. The web page can display source code, but should request it separately after the main detail page has loaded.

### 16. Secrets Abstraction

- [ ] Implement `SecretProvider` with local env/file support.
- [ ] Add a Key Vault provider behind the same interface.
- [ ] Support ServiceX config as a mounted local file and as a production secret materialized to a temp file at runtime.
- [ ] Ensure secrets are never logged, serialized to queue messages, stored in job metadata, or baked into images.
- [ ] Add tests for missing secrets, file secret lookup, and log redaction helpers.
- [ ] Verification: local fake secret tests and a documented manual check that logs do not contain secret values.

Connection to watch: web and plot-runner identities should have different secret scopes in Azure. Do not build one global "all secrets" accessor into shared code.

### 17. Azure Storage And Key Vault Adapters

- [ ] Finalize Azure Queue adapter against real Azure Storage Queue.
- [ ] Finalize Azure Blob adapter against real Azure Blob Storage.
- [ ] Finalize Key Vault provider using managed identity.
- [ ] Add configuration docs for account/container/queue creation.
- [ ] Add smoke tests or scripts that can verify queue enqueue/dequeue and blob upload/download against a dev Azure resource.
- [ ] Verification: adapter unit tests with SDK fakes/mocks plus an opt-in Azure smoke command documented for maintainers.

Connection to watch: Azurite behavior is close but not identical to Azure. Keep at least one opt-in real Azure smoke test path before calling deployment complete.

### 18. Azure Container Apps Deployment

- [ ] Add infrastructure docs or scripts for Container Apps environment, web app, Container Apps Job, Storage Account, Key Vault, database, identities, and minimal logging.
- [ ] Configure web as a tiny always-on app with low min/max replicas.
- [ ] Configure plot execution as max concurrency 1.
- [ ] Configure and document queue-triggered Container Apps Job execution from Azure Storage Queue messages.
- [ ] Wire managed identities so web and plot jobs have only required permissions.
- [ ] Verification: deploy to a dev resource group, run migrations, load web over HTTPS, submit a small job, confirm plot job starts and exits, confirm blob artifacts and DB status.

Connection to watch: deployment scripts must preserve the cost strategy. Avoid adding always-on workers, VMs, Kubernetes, or broad autoscaling as shortcuts.

### 19. Failure Handling And Recovery

- [ ] Implement behavior for missing job rows, terminal jobs, invalid queue messages, duplicate messages, runner crashes, hard timeouts, artifact upload failures, and DB update failures.
- [ ] Add retry count updates and poison-message handling policy.
- [ ] Add stale-running detection or an admin-visible recovery command.
- [ ] Add queued-job cancellation and admin cancellation controls.
- [ ] Defer user/admin running-job cancellation unless safe checkpoints are implemented.
- [ ] Ensure configured execution timeouts kill overlong Codex/script runs, preserve available partial artifacts, and mark the job failed.
- [ ] Verification: targeted tests for each failure mode and a manual local runner crash test.

Connection to watch: never delete a queue message until the durable database state is known. The queue is delivery, not truth.

### 20. Admin, Observability, And Polish

- [ ] Add admin job list with status, owner, backend profile, timestamps, failure message, and links to artifacts/logs.
- [ ] Add lightweight structured logs for job id, status transitions, runner start/end, artifact upload, and exception summaries.
- [ ] Add user-facing copy for pending approval, rejected accounts, queued jobs, failed jobs, and cancelled jobs.
- [ ] Add optional delete job/artifacts only if authorization and blob deletion behavior are fully tested.
- [ ] Tune polling intervals and page rendering after local and Azure smoke tests.
- [ ] Verification: UI tests for admin pages, log-redaction tests, and manual browser check for submit/detail/history/admin flows.

Connection to watch: polish should not change architecture. If UI work needs new data, add it through service/model boundaries rather than direct SDK calls in templates.

## Test Plan

### Fast Unit Tests

- Models: defaults, choices, timestamps, artifact metadata, approval audit fields.
- Services: job creation, status transitions, single-active-job enforcement, cancellation, ownership checks.
- Queue: minimal payload serialization, fake adapter behavior, invalid payload handling.
- Artifacts: fake store, blob key shape, content type, size, canonical artifact behavior.
- Secrets: env/file lookup, missing secret errors, redaction.
- Runner: fake success/failure, terminal job refusal, duplicate message handling.

### Django Integration Tests

- Approved user submits job and receives redirect to job detail.
- Pending/rejected user cannot submit.
- Submit creates DB row and queue message.
- Current user sees own history only.
- Staff/admin sees all jobs.
- Clone/resubmit preserves prompt/profile/dataset.
- Job detail shows queued/running/completed/failed states.
- Polling partial renders only necessary status content and stops on terminal states.
- Artifact views enforce owner/admin authorization.

### Local Service Integration Tests

- Azurite queue enqueue/receive/delete.
- Azurite blob upload/read URL/proxy/delete.
- Local runner consumes one message and completes fake job.
- Failed fake runner marks job failed and records log artifact.
- Docker Compose stack starts with web, Postgres, Azurite, and local runner.

### End-To-End Local Smoke

1. Start `docker compose up`.
2. Run migrations.
3. Create an admin and approved user.
4. Submit a tiny plot request.
5. Confirm the job becomes `queued`.
6. Confirm the local runner starts processing.
7. Confirm the fake or real plot runner marks `completed`.
8. Confirm plot/report/script/log artifacts are visible through the web page.
9. Restart the stack.
10. Confirm history and artifacts still work.

### Azure Smoke

1. Deploy web, storage, database, Key Vault, identities, and Container Apps Job.
2. Run migrations.
3. Submit a small job through HTTPS.
4. Confirm the queue-triggered Container Apps Job starts one plot job.
5. Confirm artifacts land in Blob Storage.
6. Confirm DB status becomes `completed`.
7. Confirm web result page displays artifacts and asynchronously loads generated source code/log links.
8. Confirm no analysis container remains running while idle.

## Assumptions

- This repo is currently at planning/scaffolding stage; implementation can choose file layout without preserving existing app code.
- `hep-data-web` should be used as behavior reference for UI/auth/tests, but not as an execution architecture template.
- Azure SQL is the production relational database choice because cost is a primary goal. Implementation must test SQL Server/Azure SQL compatibility rather than assuming PostgreSQL-only behavior.
- Azurite should be used from the first real local integration milestone so local development exercises queue/blob behavior early.
- Fake plot execution is required before real Codex/ServiceX execution so the portal, queue, blob, and runner contracts can be tested without credentials.
- Generated code is stored only as a blob artifact, not in the database. The job detail page should load source code asynchronously so the rest of the page appears first.
- The first Azure deployment should use queue-triggered Container Apps Jobs. Keep local execution behind the `PlotExecutor`/runner seam, but do not make the web app explicitly start production jobs unless Azure queue-triggering proves unworkable.

## Open Questions For The User

These do not block the first local milestone, but they should be resolved before Azure deployment work:

- Answered: use Azure SQL for the production database because Azure Database for PostgreSQL is considerably more expensive and the point is to keep the deployment cheap-ish.
- Answered: use queue-triggered Azure Container Apps Jobs for production plot execution so the web app remains focused on HTTP, database, and queue submission.
- Answered: do not store generated code in the database. Store source code as a blob artifact and load it asynchronously on the job detail page after the main page is displayed.
- Answered: queued-job cancellation is enough for v1. Running-job cancellation is needed eventually, but can be deferred. Add a configurable Codex/script execution timeout, initially 10 minutes, that kills overlong execution, uploads whatever partial artifacts were generated, and marks the job failed.
- Answered: keep the real plot-runner image in this repo. It will be different from `hep-data-llm` because it must include Codex and this portal's runner contract.

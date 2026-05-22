# hep-data-azure

Low-cost Django plot portal.

## Local development

The default local workflow is the Compose stack. It runs the web app, Postgres,
Azurite, and the Codex-backed local job runner together so the browser always
talks to the same backend that stores queue messages and artifacts.

1. Install dependencies for local tests and management commands:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   ```

2. Start the full stack:

   ```powershell
   docker compose up --build
   ```

That starts Postgres, Azurite, the web app, and the local job runner. The
migrate service also seeds the local `admin` and `demo` users automatically.
The local runner now invokes the real `plot-runner` path by default instead of
the fake test executor.

3. Open the app at `http://127.0.0.1:8000/`.

The host-side `manage.py runserver` path is still available for ad hoc
debugging, but it is intentionally not the default because it uses the host
SQLite workflow and can diverge from Compose.

If you need the host-only workflow anyway, run the management commands manually
instead of Compose:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_local_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

## Docker Compose details

The optional repo-owned plot-runner image is built from `Dockerfile.plot-runner`
and available through the `plot-runner` service:

```powershell
docker compose run --rm plot-runner run --job-id <uuid>
```

That command writes a per-job workdir under `tmp/plot-runner/<job_id>` with the
prompt, runner context, and generated files for inspection.

The `plot-runner` service expects `OPENAI_API_KEY` at runtime when you switch it
to Codex mode. For local development, the easiest path is to place the key in
`secrets/OPENAI_API_KEY`; the plot-runner reads mounted secrets and also honors
an explicit `OPENAI_API_KEY` environment variable. The Codex CLI is launched in
its unlocked/bypass mode inside the container so it can run non-interactively.
The key is not baked into the image. The Compose service also persists `/codex`
so Codex keeps its config, auth state, and installed skills between runs.

## Demo credentials

- Admin: `admin` / `admin123`
- Approved demo user: `demo` / `demo123`

## What works locally now

- Login and logout
- Account status page
- Job submission
- Job detail page
- Job status partial polling endpoint
- Clone/resubmit flow
- Admin approval page

The compose stack keeps job rows in Postgres, queue messages in Azurite, and
artifacts in Azurite, so a container restart should preserve completed jobs and
their outputs.

The local queue runner now runs as a separate process, and the next remaining
gap is the real plot-runner contract plus Azure-side hardening.

Useful checks:

```powershell
.\.venv\Scripts\pytest.exe tests\test_integration.py
docker compose config
```

# hep-data-azure

Low-cost Django plot portal.

## Local setup

1. Install dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   ```

2. Apply migrations:

   ```powershell
   .\.venv\Scripts\python.exe manage.py migrate
   ```

3. Create local demo users:

   ```powershell
   .\.venv\Scripts\python.exe manage.py bootstrap_local_demo
   ```

4. Start the web app:

   ```powershell
   .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
   ```

## Docker Compose

The local stack is wired for Compose as well:

```powershell
docker compose up --build
```

That starts Postgres, Azurite, the web app, and the local job runner. The migrate
service also seeds the local `admin` and `demo` users automatically.

The optional repo-owned plot-runner image is built from `Dockerfile.plot-runner`
and available through the `plot-runner` service:

```powershell
docker compose run --rm plot-runner plot_runner --job-id <uuid>
```

That command writes a per-job workdir under `tmp/plot-runner/<job_id>` with the
prompt, runner context, and generated files for inspection.

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

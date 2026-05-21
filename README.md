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

The optional repo-owned plot-runner image is available through the `plot-runner`
service:

```powershell
docker compose run --rm plot-runner plot_runner --job-id <uuid>
```

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

The local queue runner now runs as a separate process, and the next step is to
replace the filesystem artifact store with an Azurite-backed blob adapter.

The compose stack keeps job rows in Postgres and artifacts on the mounted volume,
so a container restart should preserve completed jobs and their outputs.

Useful checks:

```powershell
.\.venv\Scripts\pytest.exe tests\test_integration.py
docker compose config
```

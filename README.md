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

The current local queue is still an in-process test bridge. The next step is to replace that with a shared local queue backend so backend execution can run in a separate process.

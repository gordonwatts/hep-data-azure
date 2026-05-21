FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md uv.lock /app/
COPY hep_data_azure /app/hep_data_azure
COPY portal /app/portal
COPY templates /app/templates
COPY static /app/static
COPY manage.py /app/manage.py

RUN pip install --no-cache-dir .

EXPOSE 8000

ENTRYPOINT ["python", "manage.py"]

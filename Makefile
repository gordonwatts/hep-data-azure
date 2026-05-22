UV ?= uv
PYTHON ?= python

.PHONY: install check test lint format runserver migrate compose-up compose-down compose-config

install:
	$(UV) sync --extra dev

check:
	$(UV) run $(PYTHON) manage.py check

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .

runserver:
	$(UV) run $(PYTHON) manage.py runserver

migrate:
	$(UV) run $(PYTHON) manage.py migrate


compose-up:
	docker compose up --build

compose-down:
	docker compose down

compose-config:
	docker compose config

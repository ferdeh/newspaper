SHELL := /bin/sh

.PHONY: install build up down restart logs migrate remove-demo test lint format ps snapshot hooks verify-snapshot

install:
	./install.sh

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

snapshot:
	./scripts/export-database-snapshot.sh

hooks:
	git config core.hooksPath .githooks

verify-snapshot:
	./scripts/verify-database-snapshot.sh

migrate:
	docker compose run --rm api alembic upgrade head

remove-demo:
	docker compose run --rm api python -m app.cleanup_demo --apply

test:
	docker compose --profile test run --rm test

lint:
	docker compose run --rm api ruff check app tests
	docker compose run --rm frontend npm run lint

format:
	docker compose run --rm api ruff format app tests
	docker compose run --rm frontend npm run format

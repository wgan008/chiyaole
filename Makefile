.PHONY: install install-e2e test unit eval e2e-web lint fmt typecheck run db-up migrate android-test check

install:
	cd server && pip install -e ".[dev]"

install-e2e:
	cd server && pip install -e ".[e2e]" && playwright install chromium

unit:
	cd server && pytest tests/ -v

eval:
	cd server && pytest ../evals/ -v --eval

# Browser-driven golden-path test (server/tests_e2e/) — spins up a real uvicorn instance
# in-process (no docker-compose/postgres needed, unlike a real deployment) against an
# in-memory SQLite DB; see tests_e2e/conftest.py. Requires `make install-e2e` first.
e2e-web:
	cd server && pytest tests_e2e/ -v

test: unit

lint:
	cd server && ruff check .

fmt:
	cd server && ruff format .

typecheck:
	cd server && mypy agent/

run:
	cd server && uvicorn app.main:app --reload

db-up:
	docker compose up -d postgres

migrate:
	cd server && alembic upgrade head

android-test:
	cd android && ./gradlew testDebugUnitTest lint

# Everything CI runs.
check: lint typecheck unit

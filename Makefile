.PHONY: install lint format typecheck test frontend-check check migrate run seed demo up monitoring down

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check src tests scripts

format:
	ruff format src tests scripts

typecheck:
	mypy src

test:
	pytest --cov=spendledger --cov-report=term-missing

frontend-check:
	npm --prefix frontend ci
	npm --prefix frontend run lint
	npm --prefix frontend run build

check: lint typecheck test

migrate:
	alembic upgrade head

run:
	uvicorn spendledger.main:app --reload

seed:
	python scripts/seed_demo.py

demo:
	python scripts/run_demo.py

up:
	docker compose up --build

monitoring:
	docker compose --profile monitoring up --build

down:
	docker compose down

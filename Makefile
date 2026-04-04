.PHONY: lint format typecheck test seed serve docker-up

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy agent models services seed cli config

test:
	uv run pytest

seed:
	uv run python -m seed.seed_db --reset

serve:
	uv run uvicorn services.oms_api:app --port 8001 &
	uv run uvicorn services.wms_api:app --port 8002 &
	uv run uvicorn services.tms_api:app --port 8003 &

docker-up:
	docker compose up --build

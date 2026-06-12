.PHONY: lint format typecheck test eval demo seed serve cli stop docker-up

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy agent models services seed cli config

test:
	uv run pytest

# Interpreter eval. Default: rule arm (offline, no key). Compare arms with:
#   make eval EVAL_ARGS="--arm both"
eval:
	uv run python -m evals.run_eval $(EVAL_ARGS)

demo:
	uv run python scripts/run_demo.py

seed:
	uv run python -m seed.seed_db --reset

serve:
	uv run uvicorn services.oms_api:app --port 8001 &
	uv run uvicorn services.wms_api:app --port 8002 &
	uv run uvicorn services.tms_api:app --port 8003 &

cli:
	uv run python -m cli.interactive

stop:
	-pkill -f "uvicorn services.oms_api:app"
	-pkill -f "uvicorn services.wms_api:app"
	-pkill -f "uvicorn services.tms_api:app"

docker-up:
	docker compose up --build

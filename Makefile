.PHONY: lint format typecheck test eval eval-triage demo seed serve cli stop docker-up

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

# Interpreter eval. Default: rule arm (offline, no key). Compare arms with:
#   make eval EVAL_ARGS="--arm both"
eval:
	uv run python -m evals.run_eval $(EVAL_ARGS)

# Triage reference eval — a live Claude pass over the stuck-order gold set.
# Local only: not part of `make test`, not wired into CI (nondeterministic,
# costs tokens). Gate it with EVAL_ARGS="--min-accuracy 0.6".
eval-triage:
	uv run python -m evals.run_triage_eval $(EVAL_ARGS)

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

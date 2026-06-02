# Supply Chain Ops Assistant

> A supply-chain operations copilot — ask about orders, inventory, and shipments across OMS, WMS, and TMS in natural language. Interpretation runs on a deterministic rule-based layer today; a Claude tool-use interpreter is being layered in and measured against a labeled eval set (see [Evaluation](#evaluation)).

---

## The Problem

Supply chain operations teams live inside a fragmented toolchain. On any given morning, an ops lead might check order status in the OMS, flip to the WMS to verify inventory levels at three fulfillment centers, then open the TMS to track a carrier's SLA compliance -- all before their 9 AM standup. Each system has its own query interface, its own filter syntax, and its own export format. Cross-referencing data means pasting order IDs into spreadsheets, manually correlating shipment statuses with exception logs, and building ad-hoc pivot tables that are stale by the time anyone reads them.

After spending time with fulfillment ops teams, the pattern became clear: the information exists, but accessing it requires too much context-switching and too much manual glue. A CX rep looking up a customer's order has to know which system holds the answer. An ops lead investigating a spike in exceptions has to query two systems and mentally join the results. The cognitive overhead is not in the data -- it is in the navigation.

This project is an attempt to collapse that friction into a single conversational interface. Instead of learning three query languages, an operator types "show me all orders with delayed shipments" and the system figures out which backends to hit, how to join the results, and how to present them. The goal is not to replace the underlying systems but to provide a unified read layer that speaks the operator's language.

---

## Architecture

The system follows a **single-agent-with-tools** pattern. One copilot agent receives natural language input, interprets it into a structured query plan, routes it through confidence-based decision logic, validates it against business rules, executes it against one or more backend APIs, and formats the result for display.

```
User
  |
  v
CLI (Rich interactive prompt)
  |
  v
Copilot
  |
  +-- interpret  -->  QueryInterpreter  -->  QueryPlan (Pydantic)
  |
  +-- route      -->  ConfidenceRouter  -->  EXECUTE | EXECUTE_AND_FLAG | CLARIFY
  |
  +-- validate   -->  Validators        -->  field registry + business rules
  |
  +-- execute    -->  OpsClient (httpx)  -->  OMS API (FastAPI + SQLite)
  |                                      -->  WMS API (FastAPI + SQLite)
  |                                      -->  TMS API (FastAPI + SQLite)
  |
  v
QueryResult (Pydantic)  -->  Rich formatted tables  -->  Terminal output
```

**Why single-agent, not multi-agent?** For structured operations queries against known systems, a single agent with well-defined tools is simpler, more reliable, and easier to audit than a multi-agent handoff chain. Every query follows the same pipeline. There are no ambiguous routing decisions between agents, no message-passing protocols to debug, and no emergent behaviors to monitor. The confidence router handles the one real branching decision -- whether to execute, flag for review, or ask for clarification -- and it does so with explicit, per-intent thresholds rather than LLM-generated routing logic.

---

## Architecture Diagram

```mermaid
flowchart TD
    User([User]) --> CLI[Interactive CLI<br/><i>Rich prompt</i>]

    CLI --> Copilot[Copilot<br/><i>Orchestrator</i>]

    subgraph Agent Pipeline
        direction TB
        Copilot --> Interpret[QueryInterpreter<br/><i>NL -> QueryPlan</i>]
        Interpret --> QP[QueryPlan<br/><i>Pydantic model</i>]
        QP --> Route[ConfidenceRouter<br/><i>per-intent thresholds</i>]
        Route -->|EXECUTE| Validate[Validators<br/><i>field registry + rules</i>]
        Route -->|CLARIFY| Clarify[Request Clarification]
        Route -->|EXECUTE_AND_FLAG| Validate
        Validate --> Execute[execute_query]
    end

    subgraph Backend Services
        direction TB
        Execute --> OpsClient[OpsClient<br/><i>httpx async</i>]
        OpsClient --> OMS[OMS API<br/><i>:8001</i>]
        OpsClient --> WMS[WMS API<br/><i>:8002</i>]
        OpsClient --> TMS[TMS API<br/><i>:8003</i>]
        OMS --> OMS_DB[(oms.db)]
        WMS --> WMS_DB[(wms.db)]
        TMS --> TMS_DB[(tms.db)]
    end

    Execute --> QR[QueryResult<br/><i>Pydantic model</i>]
    QR --> Format[Rich Formatter<br/><i>tables, panels</i>]
    Format --> CLI

    Clarify --> CLI

    style QP fill:#2d5016,stroke:#4a8c2a,color:#fff
    style QR fill:#2d5016,stroke:#4a8c2a,color:#fff
```

---

## Capabilities by Persona

### Ops Lead

| Query | What it does |
|-------|-------------|
| `Show me all critical exceptions` | Lists open exceptions from the OMS filtered by severity |
| `What orders are at risk?` | Finds orders approaching their promised delivery date that haven't shipped |
| `Show me pending orders` | Lists all orders in pending status |
| `Show orders and shipments` | Cross-system join of OMS orders with TMS shipment data |

### Customer Experience Rep

| Query | What it does |
|-------|-------------|
| `Show me all orders` | Lists orders with status, customer tier, value, and center |
| `Show shipments` | Lists all shipments with carrier, status, SLA status, and tracking numbers |
| `Show me low stock items` | Surfaces inventory items below reorder point for proactive CX alerts |

### Finance / Logistics

| Query | What it does |
|-------|-------------|
| `Show SLA breaches` | Lists shipments that have breached their SLA commitments |
| `Show me all inventory` | Full inventory view across fulfillment centers |
| `Show exceptions` | Exception log with type, severity, status, and assignment |

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Docker and Docker Compose (for containerized setup)

### Option 1: Docker (recommended)

```bash
git clone https://github.com/nick-railsback/supply-chain-ops-assistant.git
cd supply-chain-ops-assistant
cp .env.example .env

# Start all services and seed the databases
docker compose up --build
```

The `docker compose` stack starts the three API services (OMS on `:8001`, WMS on `:8002`, TMS on `:8003`), seeds the databases with realistic test data, and launches the interactive copilot CLI.

### Option 2: Local Development

```bash
git clone https://github.com/nick-railsback/supply-chain-ops-assistant.git
cd supply-chain-ops-assistant
cp .env.example .env

# Install dependencies
uv sync

# Seed the databases with test data
make seed

# Start the three API services (background processes)
make serve

# Launch the interactive CLI
python -c "from cli.interactive import main; main()"
```

### Verify It Works

Once the CLI starts, you should see a health check confirming all three services are operational:

```
  Supply Chain Ops Assistant
Checking system health...
  OMS - operational
  WMS - operational
  TMS - operational

All systems operational. Type your question or /help for examples.

ops-copilot >
```

Try a query:

```
ops-copilot > Show me all pending orders
```

---

## How It Works

Here is what happens when you ask `what orders are pending`:

**1. Interpretation.** The rule-based `QueryInterpreter` matches the input against keyword/regex patterns, detecting the intent (`STATUS_CHECK`), the target system (`OMS`), the primary entity (`order`), and a `status = pending` filter. These are packed into a `QueryPlan` Pydantic model:

```python
QueryPlan(
    intent=UserIntent.STATUS_CHECK,
    target_systems=[TargetSystem.OMS],
    primary_entity="order",
    filters=[DataFilter(field="status", operator="eq", value="pending")],
    confidence=0.75,  # fixed heuristic in rule mode; a per-query signal under the LLM interpreter
    reasoning="Rule-based match for 'order' query",
)
```

> **What's rule-based vs LLM today.** The rule layer is keyword-driven and recognizes a *subset* of phrasings. It matches `what orders are pending`, but a generic `show me … orders` phrasing currently resolves to an *unfiltered* order lookup (the generic pattern matches first), and free-form queries fall through to a clarification prompt. Lifting that ceiling — free-form phrasing, robust filter extraction, and a calibrated confidence signal — is exactly what the Claude tool-use interpreter adds. The [`evals/`](evals/) harness measures both paths against gold labels so the gap is quantified, not asserted.

**2. Confidence Routing.** The `ConfidenceRouter` looks up the threshold for `status_check` intent: auto-execute at `0.75`, flag at `0.45`. Since `0.75 >= 0.75`, the decision is `EXECUTE` -- proceed without confirmation.

**3. Validation.** The `Validators` module checks each filter against the field registry. The field `("oms", "order", "status")` is registered as type `enum`, and the operator `eq` is valid for enums. No errors.

**4. Execution.** The `execute_query` function dispatches to `OpsClient.list_orders(status="pending")`, which sends an async HTTP GET to the OMS API at `localhost:8001/orders?status=pending`. The API queries the SQLite database via SQLAlchemy and returns a paginated response.

**5. Formatting.** The `QueryResult` is passed to the Rich formatter, which detects the data type as `orders` and renders a color-coded table with columns for Order ID, Status, Customer Tier, Total Value, Channel, and Center. Statuses are color-coded: `pending` in yellow, `delivered` in green, `exception` in red.

---

## Design Decisions

### Single Agent vs Multi-Agent

A multi-agent architecture (separate agents for OMS, WMS, TMS) would add coordination overhead without proportional benefit. The query space is well-defined: three systems, known entities, predictable filter patterns. A single agent with a dispatcher can handle cross-system queries via `asyncio.gather` without the complexity of inter-agent messaging. The confidence router provides the only meaningful branching logic, and it operates on explicit numeric thresholds rather than LLM-generated decisions.

### Mock APIs via HTTP vs Direct Database Access

Each backend (OMS, WMS, TMS) runs as a real FastAPI service with its own SQLite database, rather than the copilot querying databases directly. This enforces service boundaries that mirror production architecture: the copilot only knows HTTP endpoints, not schema details. It also makes the system testable with `pytest-httpx` and deployable with Docker Compose where each service is an independent container with health checks.

### Rich CLI vs Web UI

A terminal-based CLI using the Rich library provides formatted tables, color-coded statuses, and interactive prompts without the overhead of a frontend build system. Ops teams already spend significant time in terminals. Rich panels with status-aware coloring (green for delivered, yellow for in-transit, red for exceptions) convey information density that matches the operational context.

### Pydantic Everywhere

Every boundary in the system is typed with Pydantic models: `QueryPlan` between interpretation and routing, `QueryResult` between execution and formatting, `ActionProposal` for mutation requests, `PaginatedResponse[T]` for API responses. This provides validation at every handoff point and makes the data contracts self-documenting. The `from_attributes=True` config on base models enables direct SQLAlchemy ORM to Pydantic conversion.

### Per-Intent Confidence Thresholds

Not all intents carry equal risk. A `status_check` auto-executes at confidence `0.75` because a wrong read query wastes a second of compute. An `action_request` requires confidence `0.90` because a wrong mutation could escalate the wrong exceptions. The threshold table:

| Intent | Auto-Execute | Flag for Review |
|--------|-------------|----------------|
| `status_check` | 0.75 | 0.45 |
| `cross_system_query` | 0.80 | 0.50 |
| `analysis` | 0.80 | 0.50 |
| `action_request` | 0.90 | 0.60 |
| `report` | 0.75 | 0.45 |

> **On calibration:** in rule-based mode the *input* confidence is a fixed heuristic (`0.75` for any matched pattern), so routing is effectively deterministic per intent. The threshold design above is real; the signal feeding it is not yet. The Claude interpreter emits a per-query confidence along with the discrete signals behind it (are all filter fields known? is the entity unambiguous?), and the [Evaluation](#evaluation) harness reports confidence against empirical accuracy so the claim is measured rather than asserted.

---

## Test Scenarios

The test suite includes 10 scenario files in `tests/scenarios/`, each defining a natural language query with expected behavior:

| # | Scenario | Query | Intent | Systems |
|---|----------|-------|--------|---------|
| 01 | Order status check | "What is the status of order ORD-2024-000123?" | `status_check` | OMS |
| 02 | Shipment tracking | "Where is shipment SHP-20240115-00042 right now?" | `status_check` | TMS |
| 03 | Low stock inventory | "Show me all items below reorder point in the WMS" | `analysis` | WMS |
| 04 | Cross-system join | "Show me all orders that have delayed shipments" | `cross_system_query` | OMS, TMS |
| 05 | Exception summary report | "Generate a report of all open exceptions grouped by severity" | `report` | OMS |
| 06 | Resolve exception | "Resolve exception EXC-0042 as fixed" | `action_request` | OMS |
| 07 | Ambiguous query | "What about the thing from yesterday?" | `clarification_needed` | -- |
| 08 | WMS-TMS cross-system | "Show inventory items currently being shipped to fulfillment centers" | `cross_system_query` | WMS, TMS |
| 09 | Order analysis by channel | "Analyze order volume and exception rates by sales channel" | `analysis` | OMS |
| 10 | Bulk escalation | "Escalate all critical severity exceptions open for more than 24 hours" | `action_request` | OMS |

---

## Evaluation

Interpreter quality is **measured, not asserted.** The harness in [`evals/`](evals/) scores natural-language → `QueryPlan` accuracy against gold labels in `evals/dataset.jsonl` (33 cases and growing) across two arms: the deterministic **rule-based** interpreter and the **Claude** interpreter.

```bash
make eval                          # rule arm (offline, no API key)
make eval EVAL_ARGS="--arm both"   # comparative rule-vs-LLM lift table
```

**Current rule-based baseline (33 cases):**

| Metric | Rule-based |
|--------|-----------|
| Intent accuracy | 52% (17/33) |
| Target-system match | 52% (17/33) |
| Filter extraction | 25% (3/12 pairs) |
| Clarification precision / recall | 18% / 100% |

These numbers are deliberately unflattering — they quantify exactly where a keyword/regex interpreter falls short. It drops filters it has no pattern for (`show me all pending orders` → *all* orders), misclassifies `report` / `analysis` / `action_request` phrasings, and **over-clarifies**: 100% clarification recall but 18% precision means it asks for clarification on most queries it can't pattern-match rather than answering them. The confidence "signal" collapses to two constants (`0.2` / `0.75`), so the reliability table has two rows — which is itself the finding. Closing this gap with a Claude tool-use interpreter, and reporting the lift here, is the active work (see [Evaluation harness](evals/)).

---

## Project Structure

```
supply-chain-ops-assistant/
|
|-- agent/                        # Copilot agent layer
|   |-- copilot.py                # Main orchestrator: interpret -> route -> validate -> execute
|   |-- query_interpreter.py      # NL to QueryPlan (rule-based fallback, LLM-ready)
|   |-- confidence.py             # Per-intent confidence routing with three outcomes
|   |-- action_handler.py         # Action proposal generation for mutations
|   |-- report_generator.py       # Structured report generation
|   +-- validators.py             # Field registry, operator validation, status transitions
|
|-- models/                       # Pydantic models (shared data contracts)
|   |-- shared.py                 # Base classes, enums (TargetSystem, UserIntent, Severity)
|   |-- query.py                  # QueryPlan, DataFilter, QueryResult
|   |-- action.py                 # ActionProposal, ActionType
|   |-- report.py                 # ReportOutput, ReportSection
|   |-- oms.py                    # Order, LineItem, OrderException, ExceptionSummary
|   |-- wms.py                    # InventoryItem, FulfillmentCenter, StockMovement
|   +-- tms.py                    # Shipment, ShipmentWithTracking, CarrierStats, SLASummary
|
|-- services/                     # Backend API services
|   |-- common.py                 # FastAPI app factory with trace middleware and health checks
|   |-- middleware.py             # X-Trace-ID / X-Span-ID propagation middleware
|   |-- exceptions.py            # Typed service exceptions (NotFound, Unavailable, Validation)
|   |-- client.py                # OpsClient: unified async HTTP client for all three APIs
|   |-- oms_api.py               # OMS FastAPI app with SQLAlchemy ORM (orders, exceptions)
|   |-- wms_api.py               # WMS FastAPI app (inventory, centers, movements)
|   +-- tms_api.py               # TMS FastAPI app (shipments, tracking, carrier stats)
|
|-- cli/                          # Interactive terminal interface
|   +-- interactive.py           # Rich CLI with prompt loop, formatters, action confirmation
|
|-- config/                       # Configuration and prompts
|   |-- settings.py              # Pydantic Settings with per-intent confidence thresholds
|   |-- prompts.py               # LLM prompt templates (interpreter, action, report)
|   +-- logging.py               # Structured logging with trace/span context vars
|
|-- seed/                         # Test data generation
|   |-- seed_db.py               # CLI entry point: creates and populates all three databases
|   |-- generator.py             # Faker-based data generators for orders, inventory, shipments
|   |-- constants.py             # Seed data constants (SKUs, carriers, centers, channels)
|   +-- context.py               # Cross-system context for referential integrity
|
|-- tests/                        # Test suite
|   |-- conftest.py              # Shared fixtures (mock clients, test data)
|   |-- test_queries.py          # Scenario-driven query integration tests
|   |-- test_unit.py             # Unit tests for interpreter, router, validators
|   +-- scenarios/               # 10 JSON scenario files defining expected behavior
|
|-- scripts/
|   |-- run_demo.py              # Demo script for quick showcase
|   +-- seed.py                  # Alternative seed entry point
|
|-- docker-compose.yml            # Multi-service Docker stack with health checks
|-- Dockerfile                    # Multi-stage build (builder + runtime)
|-- Makefile                      # Dev commands: lint, format, typecheck, test, seed, serve
|-- pyproject.toml                # Project metadata and tool config (ruff, mypy, pytest)
+-- .env.example                  # Environment variable template
```

---

## Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | Python 3.11+ | Async-first, strong typing with `|` union syntax, ecosystem depth |
| Agent Orchestration | Custom Copilot class | Explicit pipeline stages, no framework lock-in, full auditability |
| LLM Integration | Anthropic Claude (rule-based default) | Rule-based interpreter is the working default; a Claude interpreter is attempted when `ANTHROPIC_API_KEY` is set and is being hardened to tool-use structured output. See [Evaluation](#evaluation). |
| Data Validation | Pydantic v2 | Runtime type enforcement at every boundary, JSON schema generation |
| Configuration | pydantic-settings | Typed env vars with `.env` file support and validation |
| API Framework | FastAPI | Async-native, automatic OpenAPI docs, Pydantic integration |
| HTTP Client | httpx | Async HTTP with connection pooling, timeout control, retry support |
| Database | SQLite + aiosqlite | Zero-config, file-based, async-compatible via SQLAlchemy |
| ORM | SQLAlchemy 2.0 (async) | Mapped columns, async sessions, `from_attributes` Pydantic compat |
| CLI Framework | Rich | Formatted tables, color-coded statuses, panels, spinners, prompts |
| Test Data | Faker | Realistic names, dates, addresses for seed data generation |
| Testing | pytest + pytest-asyncio | Async test support, fixture composition, scenario parameterization |
| HTTP Mocking | pytest-httpx | Intercept and mock httpx calls for isolated client testing |
| Linting | Ruff | Fast Python linter and formatter (replaces flake8 + isort + black) |
| Type Checking | mypy | Static type verification across all modules |
| Package Manager | uv | Fast dependency resolution and virtual environment management |
| Containerization | Docker + Compose | Multi-service orchestration with health checks and volume mounts |
| Observability | structlog + trace middleware | Structured JSON logs with X-Trace-ID propagation across services |

---

## Development

```bash
# Run linter
make lint

# Auto-format
make format

# Type checking
make typecheck

# Run tests
make test

# Reseed databases
make seed
```

---

## License

This project is a portfolio demonstration piece. See the repository for license details.

# Supply Chain Ops Assistant — Project Spec

## Mission

Build a production-style AI operations assistant for internal supply chain teams at a high-volume e-commerce fulfillment company. The assistant lets non-technical operators (CX reps, ops leads, finance analysts, logistics coordinators) query live operational data using natural language, take actions on that data, and generate exception reports — without needing engineering support or SQL knowledge.

This is a portfolio project. It must be polished, realistic, and clearly demonstrate: natural language data interfaces, API integration with internal systems, operational domain knowledge in fulfillment/logistics, tool-use patterns, input/output validation, and production discipline (logging, error handling, observability). The README must tell a compelling story.

---

## Context & Motivation

This project complements a separate multi-agent fulfillment triage system (fulfillment-triage-agents). That project demonstrates multi-agent orchestration, structured LLM output, hybrid scoring, human-in-the-loop gating, and a full validation/verification architecture. **This project deliberately demonstrates different skills**: a single-agent copilot with rich tool use, integration with multiple mock internal systems via REST APIs, a conversational natural language interface for non-technical users, and operational data querying and action capabilities.

Together the two projects tell a story:
1. **fulfillment-triage-agents**: "I build production-grade multi-agent systems with real validation architecture."
2. **This project**: "I understand your business and can build the internal AI tooling your ops teams actually need."

The target audience reviewing this project is an engineering hiring team at a supply chain / fulfillment SaaS company (think: a platform that powers OMS, WMS, TMS, and consumer experience for brands doing $10B+ in commerce annually). They care about: embedded problem-solving, shipping internal AI tooling at scale, API integration depth, observability, and production discipline.

---

## Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Agent Framework | **AgentField SDK (Python)** | Production agent infrastructure with built-in REST exposure, observability, structured AI output, and memory. Use `@app.reasoner()` for AI-powered query interpretation and `@app.skill()` for deterministic data operations. |
| LLM | **Claude Sonnet via `app.ai(schema=...)`** | Structured output with Pydantic schemas for query plans, action proposals, and report structures. |
| Data Models | **Pydantic v2** | Type-safe schemas for all operational entities (orders, inventory, shipments, exceptions) and all agent inputs/outputs. |
| Mock Internal APIs | **FastAPI** | Three lightweight API services simulating OMS, WMS, and TMS — the internal systems this copilot integrates with. Each runs as a separate service with its own OpenAPI spec. |
| Data Store | **SQLite** | Backing store for the mock APIs. Lightweight, zero-config, file-based. Seeded with realistic fulfillment data. |
| Seed Data | **Faker + custom generators** | Realistic operational data: order IDs, SKUs, customer names, fulfillment center codes, carrier names, tracking numbers, SLA windows, timestamps. Use domain-appropriate patterns (not obviously fake). |
| CLI Interface | **Rich** (Python library) | Polished terminal UI with formatted tables, colored status indicators, markdown rendering for reports, and a clean interactive prompt. This demonstrates "non-technical users can actually use this." |
| Containerization | **Docker Compose** | Single `docker compose up` starts all mock APIs + the agent + the AgentField control plane. |
| Language | **Python 3.11+** | Primary language throughout. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Interactive CLI (Rich)                │
│              Natural language input/output               │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              AgentField Control Plane                    │
│         http://localhost:8080 (dashboard + API)          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  Ops Copilot Agent                       │
│                                                         │
│  @app.reasoner() — interpret_query                      │
│    Takes natural language, produces a structured         │
│    QueryPlan via app.ai(schema=QueryPlan)               │
│                                                         │
│  @app.skill() — execute_query                           │
│    Routes QueryPlan to appropriate mock API(s),          │
│    aggregates results, formats response                  │
│                                                         │
│  @app.reasoner() — propose_action                       │
│    When the user requests an action, produces a          │
│    structured ActionProposal with confirmation gate      │
│                                                         │
│  @app.skill() — execute_action                          │
│    Executes confirmed actions against mock APIs          │
│                                                         │
│  @app.reasoner() — generate_report                      │
│    Produces formatted exception/summary reports          │
│    from aggregated data across all three systems         │
│                                                         │
└────────┬──────────────┬──────────────────┬──────────────┘
         │              │                  │
         ▼              ▼                  ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   OMS API    │ │   WMS API    │ │   TMS API    │
│  (FastAPI)   │ │  (FastAPI)   │ │  (FastAPI)   │
│  Port 8001   │ │  Port 8002   │ │  Port 8003   │
│              │ │              │ │              │
│  - Orders    │ │  - Inventory │ │  - Shipments │
│  - Line items│ │  - Locations │ │  - Carriers  │
│  - Customers │ │  - SKUs      │ │  - Tracking  │
│  - Exceptions│ │  - Movements │ │  - SLAs      │
│              │ │              │ │              │
│  [SQLite]    │ │  [SQLite]    │ │  [SQLite]    │
└──────────────┘ └──────────────┘ └──────────────┘
```

**Key architectural distinction from the triage project**: This is a **single agent with multiple tools** (skills and reasoners), not a multi-agent pipeline. The agent maintains conversational context across turns and dispatches to different internal APIs based on the user's intent. This deliberately shows a different agentic pattern.

---

## Project Structure

```
supply-chain-ops-assistant/
├── agent/
│   ├── copilot.py              # Main Ops Copilot agent (AgentField)
│   ├── query_interpreter.py    # NL → QueryPlan logic
│   ├── action_handler.py       # Action proposal and execution logic
│   └── report_generator.py     # Report generation logic
├── models/
│   ├── query.py                # QueryPlan, QueryResult, DataFilter
│   ├── action.py               # ActionProposal, ActionResult, ActionType enum
│   ├── report.py               # ReportRequest, ReportOutput, ExceptionSummary
│   ├── oms.py                  # Order, LineItem, Customer, OrderException
│   ├── wms.py                  # InventoryItem, FulfillmentCenter, StockMovement
│   ├── tms.py                  # Shipment, Carrier, TrackingEvent, SLAStatus
│   └── shared.py               # Shared enums, base models, timestamps
├── services/
│   ├── oms_api.py              # FastAPI app for mock OMS
│   ├── wms_api.py              # FastAPI app for mock WMS
│   ├── tms_api.py              # FastAPI app for mock TMS
│   └── client.py               # Unified API client used by the agent
├── seed/
│   ├── generator.py            # Data generation with Faker + custom logic
│   ├── seed_db.py              # Script to populate all three SQLite databases
│   └── constants.py            # Realistic domain constants (SKUs, centers, carriers)
├── cli/
│   └── interactive.py          # Rich-based interactive CLI
├── config/
│   ├── settings.py             # Configurable thresholds, API URLs, model config
│   └── prompts.py              # System prompts and prompt templates
├── tests/
│   ├── scenarios/              # End-to-end scenario test fixtures (JSON)
│   └── test_queries.py         # Automated query/response validation tests
├── scripts/
│   ├── run_demo.py             # Scripted demo that runs through key scenarios
│   └── seed.py                 # Convenience script to re-seed databases
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## Data Model — Mock Internal Systems

### OMS (Order Management System) — Port 8001

**Tables:**

`orders`:
- `order_id` (str, e.g., "ORD-2025-847291")
- `customer_id` (str)
- `customer_name` (str)
- `customer_email` (str)
- `customer_tier` (enum: standard, premium, enterprise)
- `status` (enum: pending, processing, shipped, delivered, cancelled, exception)
- `channel` (enum: dtc_web, dtc_mobile, wholesale_b2b, marketplace_amazon, marketplace_shopify)
- `created_at` (datetime)
- `updated_at` (datetime)
- `promised_delivery_date` (date)
- `fulfillment_center_id` (str)
- `total_value` (float)
- `currency` (str, default "USD")
- `line_item_count` (int)
- `notes` (str, nullable)

`line_items`:
- `line_item_id` (str)
- `order_id` (str, FK)
- `sku` (str, e.g., "NTV-DEOD-EUCL-3PK")
- `product_name` (str)
- `quantity` (int)
- `unit_price` (float)
- `status` (enum: pending, allocated, picked, packed, shipped, backordered)

`order_exceptions`:
- `exception_id` (str)
- `order_id` (str, FK)
- `exception_type` (enum: address_invalid, payment_failed, item_backordered, sla_at_risk, damaged_in_warehouse, wrong_item_picked, customer_requested_cancel, carrier_rejection)
- `severity` (enum: low, medium, high, critical)
- `status` (enum: open, investigating, resolved, escalated)
- `created_at` (datetime)
- `resolved_at` (datetime, nullable)
- `description` (str)
- `assigned_to` (str, nullable — ops team member name)

**Endpoints:**
- `GET /orders` — list/filter orders (query params: status, channel, customer_tier, fulfillment_center_id, date_from, date_to, min_value, max_value)
- `GET /orders/{order_id}` — single order with line items
- `GET /orders/at-risk` — orders where promised_delivery_date is approaching and status is not yet shipped
- `GET /exceptions` — list/filter exceptions (query params: exception_type, severity, status, date_from, date_to)
- `GET /exceptions/summary` — aggregate counts by type and severity
- `PATCH /orders/{order_id}` — update order (status, notes)
- `PATCH /exceptions/{exception_id}` — update exception (status, assigned_to)
- `GET /stats/daily` — daily order volume, value, exception rate

### WMS (Warehouse Management System) — Port 8002

**Tables:**

`fulfillment_centers`:
- `center_id` (str, e.g., "FC-ATL-01", "FC-LAX-02", "FC-ORD-01")
- `name` (str, e.g., "Atlanta Hub", "Los Angeles West", "Chicago Central")
- `region` (str, e.g., "Southeast", "West", "Midwest")
- `capacity_units` (int — total storage units)
- `current_utilization` (float — 0.0 to 1.0)
- `active` (bool)

`inventory`:
- `inventory_id` (str)
- `sku` (str)
- `product_name` (str)
- `fulfillment_center_id` (str, FK)
- `quantity_on_hand` (int)
- `quantity_allocated` (int)
- `quantity_available` (int — on_hand minus allocated)
- `reorder_point` (int)
- `last_counted_at` (datetime)
- `category` (str, e.g., "Health & Beauty", "Nutrition", "Apparel", "Accessories")

`stock_movements`:
- `movement_id` (str)
- `sku` (str)
- `fulfillment_center_id` (str, FK)
- `movement_type` (enum: inbound_receipt, outbound_pick, adjustment_positive, adjustment_negative, transfer_in, transfer_out)
- `quantity` (int)
- `reference_id` (str — order_id or PO number)
- `timestamp` (datetime)

**Endpoints:**
- `GET /inventory` — list/filter inventory (query params: sku, fulfillment_center_id, category, below_reorder_point=true)
- `GET /inventory/low-stock` — items where quantity_available < reorder_point
- `GET /centers` — list fulfillment centers with utilization
- `GET /centers/{center_id}/inventory` — all inventory at a specific center
- `GET /movements` — recent stock movements (query params: sku, center_id, movement_type, date_from, date_to)
- `GET /stats/utilization` — capacity utilization across all centers

### TMS (Transportation Management System) — Port 8003

**Tables:**

`shipments`:
- `shipment_id` (str, e.g., "SHP-20250402-93847")
- `order_id` (str, FK into OMS)
- `carrier` (str, e.g., "FedEx", "UPS", "USPS", "OnTrac", "LSO")
- `service_level` (str, e.g., "Ground", "2Day", "NextDay", "Economy")
- `status` (enum: label_created, picked_up, in_transit, out_for_delivery, delivered, exception, returned)
- `tracking_number` (str)
- `origin_center_id` (str)
- `destination_zip` (str)
- `destination_state` (str)
- `weight_lbs` (float)
- `shipping_cost` (float)
- `label_created_at` (datetime)
- `estimated_delivery` (datetime)
- `actual_delivery` (datetime, nullable)
- `sla_target` (datetime — the promise date from OMS)
- `sla_status` (enum: on_track, at_risk, breached, met)

`tracking_events`:
- `event_id` (str)
- `shipment_id` (str, FK)
- `timestamp` (datetime)
- `location` (str)
- `status` (str)
- `description` (str)

**Endpoints:**
- `GET /shipments` — list/filter shipments (query params: carrier, status, sla_status, origin_center_id, date_from, date_to)
- `GET /shipments/{shipment_id}` — single shipment with tracking events
- `GET /shipments/sla-breaches` — shipments where sla_status is "breached" or "at_risk"
- `GET /shipments/by-order/{order_id}` — shipments for a specific order
- `GET /stats/carrier-performance` — on-time rate, avg transit days, cost per shipment by carrier
- `GET /stats/sla-summary` — SLA compliance rates by carrier and service level
- `PATCH /shipments/{shipment_id}` — update shipment (status, notes)

---

## Seed Data Requirements

Generate **realistic, internally consistent** data that tells a coherent operational story. The data should look like a real snapshot of a fulfillment operation, not random noise.

**Volume:**
- 500 orders spanning the last 30 days
- ~1,200 line items across those orders
- 40-60 open exceptions (plus 100+ resolved ones)
- 5 fulfillment centers across US regions
- 80-100 unique SKUs across 5 product categories
- 500 shipments with tracking events
- Realistic carrier mix (FedEx ~35%, UPS ~30%, USPS ~20%, regional ~15%)

**Consistency rules:**
- Every shipped order must have a corresponding shipment in TMS
- Shipment origin_center_id must match the order's fulfillment_center_id
- inventory.quantity_allocated should roughly correspond to pending/processing orders
- Items that are backordered in OMS should show quantity_available near zero in WMS
- SLA breaches in TMS should correspond to orders that have exception records in OMS
- A few fulfillment centers should be running hot (>85% utilization) to create realistic operational pressure
- Temporal patterns: order volume should be higher on weekdays, with a visible spike 2-3 days ago simulating a flash sale

**Use realistic-sounding brand/product names** inspired by the DTC e-commerce space (health, beauty, nutrition, apparel, accessories). Example SKUs: "AG1-POUCH-30SRV", "NTV-DEOD-CCNT-2PK", "TULA-CLNS-ROSE-4OZ". Example product names: "Daily Greens Pouch (30 Servings)", "Coconut Vanilla Deodorant 2-Pack", "Rose Glow Cleanser 4oz".

---

## Agent Behavior — Ops Copilot

### Core Capabilities

The agent must handle the following categories of natural language queries:

**1. Status Queries (read-only, single system)**
- "How many orders came in today?"
- "What's the current status of order ORD-2025-847291?"
- "Show me all open exceptions"
- "What's the inventory level for SKU AG1-POUCH-30SRV?"

**2. Cross-System Queries (read-only, multiple systems)**
- "Which orders from the last 24 hours are at risk of missing their SLA?" (requires OMS + TMS)
- "For the orders stuck in processing, where's the inventory bottleneck?" (requires OMS + WMS)
- "Show me carrier performance for shipments out of the Atlanta hub this week" (requires TMS + WMS for center name resolution)

**3. Analytical Queries (aggregation and insight)**
- "What are the top 5 SKUs by backorder rate this week?"
- "Which fulfillment center has the highest exception rate?"
- "Compare FedEx vs UPS on-time delivery for the last 7 days"
- "Give me a daily order volume trend for the past two weeks"

**4. Action Requests (write operations with confirmation)**
- "Flag all SLA-at-risk orders for expedited shipping"
- "Assign all open critical exceptions to Sarah Chen"
- "Mark exception EXC-8847 as resolved"
- "Escalate order ORD-2025-847291 — the customer is enterprise tier and their shipment is 3 days late"

**5. Report Generation**
- "Generate an exception report for the morning ops standup"
- "Give me a fulfillment center health check"
- "Prepare an SLA compliance summary for this week"

### Query Interpretation Flow

When a user sends a natural language query, the agent should:

1. **Interpret** — Use `app.ai(schema=QueryPlan)` to produce a structured query plan that identifies:
   - Which system(s) to query (OMS, WMS, TMS, or multiple)
   - What filters to apply
   - What aggregation is needed
   - What the user's intent is (status check, analysis, action request, report)
   - Confidence level in the interpretation

2. **Validate the interpretation** — Before executing, check:
   - Are the requested filters valid for the target API?
   - Does the query reference specific IDs that should exist?
   - If confidence is below threshold (configurable, default 0.7), ask the user for clarification instead of guessing

3. **Execute** — Call the appropriate mock API endpoint(s) via the unified API client. For cross-system queries, call multiple APIs and join the results.

4. **Format and present** — Return results in a clean, human-readable format using Rich tables, colored status indicators, and plain-language summaries. Always lead with the key finding, then present supporting data.

### Action Confirmation Gate

For any write operation (PATCH calls), the agent must:

1. Present a clear summary of what it proposes to do: "I'll update 7 shipments to expedited status. Here they are: [table]"
2. Ask for explicit confirmation: "Proceed? (y/n)"
3. Only execute after confirmation
4. Report results: "Done. 7 shipments updated. 1 failed (SHP-20250402-93847 — carrier rejected expedite request)."
5. Log the action, who confirmed it, and the outcome

This is the equivalent of the human-in-the-loop pattern from the triage project, but adapted for an interactive copilot context.

---

## Pydantic Models — Agent I/O Schemas

Define these precisely. The agent's LLM calls must produce structured output via `app.ai(schema=...)`.

### QueryPlan

```python
class TargetSystem(str, Enum):
    OMS = "oms"
    WMS = "wms"
    TMS = "tms"

class UserIntent(str, Enum):
    STATUS_CHECK = "status_check"
    CROSS_SYSTEM_QUERY = "cross_system_query"
    ANALYSIS = "analysis"
    ACTION_REQUEST = "action_request"
    REPORT = "report"
    CLARIFICATION_NEEDED = "clarification_needed"

class DataFilter(BaseModel):
    field: str
    operator: str  # eq, gt, lt, gte, lte, in, between, like
    value: Any

class QueryPlan(BaseModel):
    intent: UserIntent
    target_systems: list[TargetSystem]
    primary_entity: str  # "orders", "shipments", "inventory", "exceptions", etc.
    filters: list[DataFilter]
    aggregation: str | None  # "count", "sum", "avg", "group_by", etc.
    sort_by: str | None
    limit: int | None
    requires_join: bool  # True if cross-system correlation needed
    join_key: str | None  # e.g., "order_id", "sku", "fulfillment_center_id"
    confidence: float
    reasoning: str  # Brief explanation of interpretation
```

### ActionProposal

```python
class ActionType(str, Enum):
    UPDATE_ORDER_STATUS = "update_order_status"
    UPDATE_EXCEPTION = "update_exception"
    ASSIGN_EXCEPTION = "assign_exception"
    ESCALATE_ORDER = "escalate_order"
    FLAG_SHIPMENTS = "flag_shipments"
    BULK_UPDATE = "bulk_update"

class ActionProposal(BaseModel):
    action_type: ActionType
    target_ids: list[str]
    changes: dict[str, Any]
    reasoning: str
    impact_summary: str  # Human-readable: "This will update 7 shipments..."
    risk_level: str  # low, medium, high
    requires_confirmation: bool  # Always True for now
```

### ReportOutput

```python
class ReportSection(BaseModel):
    title: str
    content: str  # Markdown-formatted
    data_table: list[dict] | None  # For Rich table rendering
    highlight: str | None  # Key callout, e.g., "3 critical exceptions need attention"

class ReportOutput(BaseModel):
    report_type: str  # "exception_summary", "sla_compliance", "center_health", etc.
    title: str
    generated_at: datetime
    sections: list[ReportSection]
    action_items: list[str]  # Recommended next steps
```

---

## CLI Interface

Use **Rich** to build a polished interactive terminal experience.

**Features:**
- A persistent prompt loop: `ops-copilot > ` where the user types natural language
- Results rendered as Rich tables with colored status columns (green=good, yellow=warning, red=critical)
- Reports rendered as Rich markdown panels
- Action confirmation prompts with clear [y/n] input
- A startup banner showing system health (pings all three mock APIs, shows status)
- Special commands:
  - `/help` — show example queries by category
  - `/status` — show system health (API connectivity, data freshness)
  - `/history` — show recent queries in the session
  - `/exit` — clean shutdown

**UX philosophy:** This is designed for an ops team lead at 8am who needs answers fast. Responses should be concise, lead with the key finding, and use color to draw the eye to what matters. Don't bury the insight in a wall of text.

---

## Validation & Quality

Apply validation patterns proportional to the project scope (lighter than the triage project, but present):

**Input validation:**
- The QueryPlan's confidence score drives behavior: high confidence → execute; low confidence → ask for clarification
- Validate that referenced IDs (order IDs, SKUs, center IDs) exist before executing queries
- Sanitize natural language input (strip injection-style patterns, though note this in README as a production concern, not a full implementation)

**Output validation:**
- All API responses are parsed through Pydantic models — malformed data from mock APIs raises clear errors
- Cross-system joins validate that join keys actually match (e.g., an order_id from OMS exists in TMS results)
- Report generation validates that data tables are non-empty before including a section

**Action safety:**
- All write operations require explicit confirmation
- Bulk updates are capped at a configurable limit (default: 50) with a warning if more would be affected
- Every action is logged with timestamp, user confirmation, target IDs, changes made, and outcome

---

## Tests

### Scenario Tests (`tests/scenarios/`)

Create JSON fixtures that define end-to-end scenarios. Each fixture specifies:
- `query` — the natural language input
- `expected_intent` — the UserIntent the agent should identify
- `expected_systems` — which system(s) should be queried
- `expected_result_contains` — key strings or patterns the response should contain
- `expected_result_count` — approximate number of results (for list queries)

**Scenarios to include:**

1. `simple_order_lookup.json` — Look up a specific order by ID
2. `open_exceptions_list.json` — "Show me all open critical exceptions"
3. `cross_system_sla_risk.json` — "Which orders are at risk of missing SLA?" (must query OMS + TMS)
4. `inventory_bottleneck.json` — "What SKUs are below reorder point at the Atlanta hub?"
5. `carrier_comparison.json` — "Compare FedEx vs UPS this week"
6. `action_assign_exceptions.json` — "Assign all open critical exceptions to Mike Torres"
7. `ambiguous_query.json` — "What's going on?" (should trigger clarification, not a guess)
8. `report_morning_standup.json` — "Generate the morning ops standup report"
9. `nonexistent_order.json` — "What's the status of order ORD-FAKE-999?" (should handle gracefully)
10. `complex_analytical.json` — "Which fulfillment center has the highest ratio of SLA breaches to total shipments this week?"

### Automated Tests (`tests/test_queries.py`)

A test runner script that:
- Seeds fresh test databases
- Starts mock API services
- Runs each scenario through the agent
- Validates that the intent was correctly identified
- Validates that the correct systems were queried
- Validates that the response contains expected content
- Produces a pass/fail summary

---

## README

The README is a critical deliverable. It should be thorough and tell a story — not just list features. Structure it as follows:

### Title and Tagline
`supply-chain-ops-assistant` — "A natural language operations copilot for supply chain teams, built on AgentField."

### The Problem (2-3 paragraphs)
Frame this as the discovery process of an embedded engineer. Describe the operational reality: ops team leads start their day by manually querying 3 different systems (OMS, WMS, TMS), cross-referencing data in spreadsheets, and building exception reports by hand. A CX rep who needs to quickly check an order's shipment status has to look it up in one system, find the shipment ID, switch to another system, search for the tracking info, and piece together the answer. Finance analysts pull data from all three systems to reconcile shipping costs.

This manual cross-system work is exactly the kind of friction that AI can eliminate — not by replacing the people, but by giving them a single natural language interface that understands their questions and knows how to query the right systems.

### Architecture
Include the ASCII architecture diagram from this spec. Explain the single-agent-with-tools pattern and why it's appropriate here (contrast briefly with multi-agent patterns — reference the triage project if appropriate, but keep it subtle).

### Architecture Diagram (Mermaid)
Include a mermaid diagram that shows:
- User input flowing into the CLI
- The CLI passing to the AgentField Control Plane
- The Ops Copilot Agent with its reasoners and skills as internal components
- The three mock API services (OMS, WMS, TMS) each with their own data store
- The query interpretation → validation → execution → formatting pipeline within the agent
- The action confirmation gate for write operations
- Color coding to distinguish the agent layer, the API layer, and the data layer
- Annotations showing Pydantic model names at each boundary (QueryPlan, ActionProposal, ReportOutput)

### Capabilities
Organize by user persona:
- **For Ops Team Leads**: status checks, exception triage, morning standup reports
- **For CX Reps**: quick order/shipment lookups, customer-facing status summaries
- **For Finance/Analytics**: carrier cost comparisons, SLA compliance reports, volume trends

Show 2-3 real example query/response pairs for each persona — formatted as terminal screenshots or code blocks showing the Rich output.

### Quick Start
```
cp .env.example .env
# Add your ANTHROPIC_API_KEY
docker compose up --build
# In another terminal:
python scripts/seed.py          # Seed databases with realistic data
python cli/interactive.py       # Start the copilot
```

### How It Works (Technical)
Walk through the lifecycle of a query:
1. Natural language input
2. LLM interprets → structured QueryPlan
3. Confidence check (ask for clarification if unsure)
4. API dispatch (single or multi-system)
5. Result aggregation and formatting
6. Rich terminal output

Highlight the validation at each step.

### Design Decisions
Explain key choices:
- Why a single agent with tools vs. multi-agent (fits the interactive copilot use case; contrast with the triage project)
- Why mock APIs instead of a monolithic data layer (demonstrates real integration patterns — the agent talks to services via HTTP, just like production)
- Why Rich CLI instead of a web UI (ships faster, demonstrates UX thinking without frontend overhead, ops teams live in terminals)
- Why AgentField (production infrastructure: observability, REST exposure, structured AI, memory)

### Test Scenarios
Table of all test scenarios with expected behavior.

### Project Structure
The file tree from this spec.

### Stack
The tech stack table from this spec.

---

## Docker Compose

```yaml
services:
  agentfield:
    image: agentfield/control-plane:latest
    ports:
      - "8080:8080"

  oms-api:
    build:
      context: .
      dockerfile: Dockerfile
    command: uvicorn services.oms_api:app --host 0.0.0.0 --port 8001
    ports:
      - "8001:8001"
    volumes:
      - ./data:/app/data

  wms-api:
    build:
      context: .
      dockerfile: Dockerfile
    command: uvicorn services.wms_api:app --host 0.0.0.0 --port 8002
    ports:
      - "8002:8002"
    volumes:
      - ./data:/app/data

  tms-api:
    build:
      context: .
      dockerfile: Dockerfile
    command: uvicorn services.tms_api:app --host 0.0.0.0 --port 8003
    ports:
      - "8003:8003"
    volumes:
      - ./data:/app/data

  copilot:
    build:
      context: .
      dockerfile: Dockerfile
    command: python agent/copilot.py
    depends_on:
      - agentfield
      - oms-api
      - wms-api
      - tms-api
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - AGENTFIELD_URL=http://agentfield:8080
      - OMS_API_URL=http://oms-api:8001
      - WMS_API_URL=http://wms-api:8002
      - TMS_API_URL=http://tms-api:8003
```

---

## Implementation Priority

If time is constrained, build in this order — each layer is independently demoable:

1. **Seed data + Mock APIs** — Get the three FastAPI services running with realistic data. This is the foundation.
2. **Pydantic models** — All agent I/O schemas, all API response models.
3. **Agent core** — The copilot agent with query interpretation and single-system queries working.
4. **CLI** — Rich-based interactive interface. At this point you have a working demo.
5. **Cross-system queries** — Multi-API queries with join logic.
6. **Actions** — Write operations with confirmation gate.
7. **Reports** — Formatted report generation.
8. **Tests** — Scenario fixtures and automated validation.
9. **README** — The full narrative README with mermaid diagram.
10. **Docker Compose** — Containerized deployment.

**Minimum viable demo** = items 1-4. Everything after that adds depth.

---

## Implementation Notes

- Preserve clean separation: agent logic should not import FastAPI models directly — it should talk to mock APIs via HTTP using the unified client in `services/client.py`. This is the whole point of demonstrating integration patterns.
- Use `httpx` (async) for the API client, not `requests`.
- All timestamps should be timezone-aware (UTC).
- Log every LLM call with the input, output, latency, and token count. Use Python `logging` with structured JSON output.
- The AgentField dashboard at localhost:8080 should show the agent's execution timeline — mention this in the README as the observability layer.
- Use type hints throughout. No `Any` types except in the QueryPlan's filter value field (which must accept multiple types by design).
- Keep prompts in `config/prompts.py`, not scattered inline. Each prompt should have a clear docstring explaining its purpose.
- The mock APIs should have OpenAPI docs enabled (FastAPI does this automatically at `/docs`) — mention this in the README as showing API-first design.
"""Protocol-level pins for a not-yet-built stdio MCP server.

Nothing under ``mcp_server/`` exists yet, and the third-party ``mcp`` SDK is not
yet a project dependency, so every test that touches either name reaches it
through a lazy import inside its own body rather than a module-level
``import`` — the same technique this repo already uses for a package pinned
before it exists: a missing module then surfaces as a per-test failure
instead of a collection error, which this suite's harness treats very
differently.

Every assertion that touches tool behaviour goes through the real client
SDK's request dispatch against a live subprocess speaking stdio, the way an
actual client would, rather than importing and calling a private async
function directly: a function can stay correct while never being registered,
never named right, or never reachable over the wire, and that gap is exactly
what a protocol-level check closes. A handful of tests instead read the
package's own build metadata (``pyproject.toml``, ``uv.lock``) or its parsed
source, because the property they pin is structural rather than a runtime
response.
"""

import ast
import asyncio
import json
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

TOOL_NAMES = {"list_stuck_orders", "get_order_triage_context", "get_carrier_stats"}

# A bare module run, no subcommand, no flags: the shape every other
# standalone entrypoint in this project already uses (the CLI, the seeder,
# the eval runner all run as `python -m <package>`).
SERVER_ARGS = ("-m", "mcp_server")

# Generous ceilings meant to catch a genuine hang, not to time performance.
INIT_TIMEOUT = 20.0
CALL_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Locating the repo and the two not-yet-existing packages, read lazily
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _import_mcp() -> Any:
    import mcp

    return mcp


# ---------------------------------------------------------------------------
# Talking to a live server subprocess the way a real client would
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _client_session(env: dict[str, str] | None = None):
    """A client session against a freshly spawned server subprocess.

    The subprocess speaks only what its stdin/stdout carry; nothing here
    knows or needs to know a port.
    """
    mcp = _import_mcp()
    params = mcp.StdioServerParameters(
        command=sys.executable,
        args=list(SERVER_ARGS),
        cwd=str(_repo_root()),
        env=env,
    )
    async with mcp.stdio_client(params) as (read_stream, write_stream):
        async with mcp.ClientSession(read_stream, write_stream) as session:
            # A hang here means the process never answered the handshake at
            # all — the clearest possible sign of an interactive or broken
            # entrypoint, so it must fail loudly rather than stall the suite.
            await asyncio.wait_for(session.initialize(), timeout=INIT_TIMEOUT)
            yield session


async def _call(session: Any, name: str, arguments: dict[str, Any] | None = None) -> Any:
    return await asyncio.wait_for(session.call_tool(name, arguments or {}), timeout=CALL_TIMEOUT)


async def _list(session: Any) -> Any:
    return await asyncio.wait_for(session.list_tools(), timeout=CALL_TIMEOUT)


@asynccontextmanager
async def _live_services(oms_app: Any, wms_app: Any, tms_app: Any):
    """Serve the three shared test apps on real TCP ports.

    A spawned subprocess is a different OS process, so it cannot reach an
    in-process ASGI transport the way the rest of this suite's tests do; only
    a real socket bridges the process boundary. Bound to an OS-assigned port
    so nothing collides with a fixed port another process on the machine may
    already hold.
    """
    import uvicorn

    servers: list[tuple[Any, asyncio.Task[None]]] = []
    try:
        urls: dict[str, str] = {}
        for env_key, app in (
            ("OMS_API_URL", oms_app),
            ("WMS_API_URL", wms_app),
            ("TMS_API_URL", tms_app),
        ):
            config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
            server = uvicorn.Server(config)
            sock = config.bind_socket()
            task = asyncio.create_task(server.serve(sockets=[sock]))
            servers.append((server, task))
            while not server.started:
                await asyncio.sleep(0.01)
            urls[env_key] = f"http://127.0.0.1:{sock.getsockname()[1]}"
        yield urls
    finally:
        for server, task in servers:
            server.should_exit = True
            await task


# ---------------------------------------------------------------------------
# Reading a tool's answer regardless of which channel carried it
# ---------------------------------------------------------------------------


def _tool_payload(result: Any) -> Any:
    """The tool's returned value, whether it rode structured or text content."""
    if result.structured_content is not None:
        return result.structured_content
    for block in result.content:
        text = getattr(block, "text", None)
        if text is not None:
            return json.loads(text)
    raise AssertionError(f"a successful call_tool result carried no readable payload: {result!r}")


def _extract_order_ids(payload: Any) -> set[str]:
    """The set of order ids named in a stuck-orders answer, whatever its wrapping."""
    items = payload
    if isinstance(payload, dict):
        list_values = [v for v in payload.values() if isinstance(v, list)]
        assert len(list_values) == 1, f"cannot find a single list of orders in {payload!r}"
        items = list_values[0]
    assert isinstance(items, list), f"a stuck-orders payload is not a list: {payload!r}"
    ids: set[str] = set()
    for item in items:
        if isinstance(item, str):
            ids.add(item)
        elif isinstance(item, dict):
            order_id = item.get("order_id") or item.get("id")
            assert order_id, f"cannot find an order id in {item!r}"
            ids.add(order_id)
        else:
            raise AssertionError(f"unexpected item shape in a stuck-orders payload: {item!r}")
    return ids


def _assert_no_root_cause_leak(payload: Any, where: str) -> None:
    if isinstance(payload, dict):
        keys = {str(k).lower() for k in payload}
        assert "label" not in keys, f"{where}: a 'label' field is present in {payload!r}"
        assert "root_cause" not in keys, f"{where}: a 'root_cause' field is present in {payload!r}"
        for value in payload.values():
            _assert_no_root_cause_leak(value, where)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_root_cause_leak(item, where)


# ---------------------------------------------------------------------------
# Supplementary fixture data the shared apps don't already carry
# ---------------------------------------------------------------------------


async def _seed_picking_status_order(oms_app: Any) -> str:
    """A resolvable order whose one line item carries a status the schema never declared.

    Reproduces a pre-existing defect in the shared OMS backend: reading this
    row 500s at the HTTP layer instead of serializing.
    """
    from services.oms_api import LineItemORM, OrderORM, get_session as oms_get_session

    order_id = "ORD-2025-900"
    gen = oms_app.dependency_overrides[oms_get_session]()
    session = await anext(gen)
    session.add(
        OrderORM(
            order_id=order_id,
            customer_id="CUST-900",
            customer_name="Peggy Picking",
            customer_email="peggy@example.com",
            customer_tier="standard",
            status="processing",
            channel="dtc_web",
            created_at="2025-03-06T10:00:00",
            updated_at="2025-03-06T10:00:00",
            promised_delivery_date="2025-03-20T10:00:00",
            fulfillment_center_id="FC-EAST",
            total_value=50.0,
            currency="USD",
            line_item_count=1,
            notes=None,
        )
    )
    session.add(
        LineItemORM(
            line_item_id="LI-00000900",
            order_id=order_id,
            sku="SKU-A100",
            product_name="Widget A",
            quantity=1,
            unit_price=50.0,
            status="picking",
        )
    )
    await session.commit()
    await gen.aclose()
    return order_id


async def _seed_bulk_stuck_orders(oms_app: Any, count: int) -> None:
    """`count` orders that are unambiguously stuck: non-terminal, promised long past."""
    from services.oms_api import OrderORM, get_session as oms_get_session

    gen = oms_app.dependency_overrides[oms_get_session]()
    session = await anext(gen)
    session.add_all(
        [
            OrderORM(
                order_id=f"ORD-BULK-{i:05d}",
                customer_id=f"CUST-BULK-{i:05d}",
                customer_name="Bulk Customer",
                customer_email="bulk@example.com",
                customer_tier="standard",
                status="processing",
                channel="dtc_web",
                created_at="2020-01-01T00:00:00",
                updated_at="2020-01-01T00:00:00",
                promised_delivery_date="2020-01-02T00:00:00",
                fulfillment_center_id="FC-EAST",
                total_value=10.0,
                currency="USD",
                line_item_count=0,
                notes=None,
            )
            for i in range(count)
        ]
    )
    await session.commit()
    await gen.aclose()


# ---------------------------------------------------------------------------
# Reading the package's own source, statically, before it is importable
# ---------------------------------------------------------------------------


def _mcp_server_modules() -> list[Path]:
    package = _repo_root() / "mcp_server"
    assert package.is_dir(), f"no mcp_server package at {package}"
    modules = sorted(package.rglob("*.py"))
    assert modules, f"the mcp_server package at {package} contains no modules"
    return modules


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> fully-qualified target, for every import in a module."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                aliases[local] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _dotted(node: ast.AST | None) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _resolve(dotted: str, aliases: dict[str, str]) -> str:
    head, _, rest = dotted.partition(".")
    resolved = aliases.get(head, head)
    return f"{resolved}.{rest}" if rest else resolved


_BANNED_TRANSPORT_CALL_PREFIXES = (
    "socket.socket",
    "asyncio.start_server",
    "uvicorn.run",
    "uvicorn.Server",
    "mcp.server.sse",
    "mcp.server.streamable_http",
)
_BANNED_TRANSPORT_LITERALS = {"sse", "streamable-http", "streamable_http"}


def _port_socket_sse_hits(source: str, label: str) -> list[str]:
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        if dotted is not None:
            resolved = _resolve(dotted, aliases)
            if any(
                resolved == prefix or resolved.startswith(prefix + ".")
                for prefix in _BANNED_TRANSPORT_CALL_PREFIXES
            ):
                hits.append(f"{label}:{node.lineno} calls {resolved}(...)")
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Constant) and arg.value in _BANNED_TRANSPORT_LITERALS:
                hits.append(f"{label}:{node.lineno} passes transport={arg.value!r}")
    return hits


_MUTATING_METHOD_NAMES = {"update_order", "update_exception", "update_inventory", "update_shipment"}


def _mutating_call_hits(source: str, label: str) -> list[str]:
    tree = ast.parse(source)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _MUTATING_METHOD_NAMES:
                hits.append(f"{label}:{node.lineno} calls a `.{node.func.attr}(...)` attribute")
    return hits


def _direct_backend_call_hits(source: str, label: str) -> list[str]:
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            if dotted is not None:
                resolved = _resolve(dotted, aliases)
                if resolved in ("httpx.AsyncClient", "httpx.Client"):
                    hits.append(f"{label}:{node.lineno} constructs {resolved}(...) directly")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.match(r"^https?://", node.value):
                hits.append(f"{label}:{node.lineno} hardcodes a URL literal {node.value!r}")
    return hits


def _stdout_write_hits(source: str, label: str) -> list[str]:
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        if dotted is not None:
            resolved = _resolve(dotted, aliases)
            if resolved == "print" or resolved.startswith("sys.stdout."):
                hits.append(f"{label}:{node.lineno} calls {resolved}(...)")
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            arg_dotted = _dotted(arg)
            if arg_dotted is not None and _resolve(arg_dotted, aliases) == "sys.stdout":
                hits.append(f"{label}:{node.lineno} references sys.stdout")
    return hits


def _load_toml(path: Path) -> dict[str, Any]:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The tool surface: exactly three names, declared once, read-only
# ---------------------------------------------------------------------------


async def test_exactly_three_tools_are_registered():
    async with _client_session() as session:
        result = await _list(session)
    names = {tool.name for tool in result.tools}
    assert names == TOOL_NAMES, f"registered tool set is {names}, expected exactly {TOOL_NAMES}"


async def test_the_declared_tool_set_is_static_within_a_session():
    async with _client_session() as session:
        first = {tool.name for tool in (await _list(session)).tools}
        second = {tool.name for tool in (await _list(session)).tools}
    assert first, "the first listing returned no tools at all"
    assert first == second, f"two listings in one session disagreed: {first} != {second}"


def test_no_module_binds_a_port_socket_or_sse_transport():
    # the positive half -- the server actually answers over stdio -- is
    # exercised by every live protocol call elsewhere in this file
    hits: list[str] = []
    root = _repo_root()
    for path in _mcp_server_modules():
        hits += _port_socket_sse_hits(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
    assert not hits, "a network transport surface was found:\n" + "\n".join(hits)


async def test_every_tool_declares_itself_read_only():
    async with _client_session() as session:
        result = await _list(session)
    not_marked = [
        tool.name
        for tool in result.tools
        if tool.annotations is None or tool.annotations.read_only_hint is not True
    ]
    assert not not_marked, f"tools missing a read_only_hint=True annotation: {not_marked}"


# ---------------------------------------------------------------------------
# Read-only, structurally: no path to a write, no path around the client
# ---------------------------------------------------------------------------


def test_no_module_calls_a_mutating_ops_client_method():
    hits: list[str] = []
    root = _repo_root()
    for path in _mcp_server_modules():
        hits += _mutating_call_hits(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
    assert not hits, "a call into the mutating surface was found:\n" + "\n".join(hits)


def test_every_backend_call_goes_through_the_shared_client():
    hits: list[str] = []
    root = _repo_root()
    for path in _mcp_server_modules():
        hits += _direct_backend_call_hits(
            path.read_text(encoding="utf-8"), str(path.relative_to(root))
        )
    assert not hits, "a call bypassing the shared backend client was found:\n" + "\n".join(hits)


# ---------------------------------------------------------------------------
# get_order_triage_context
# ---------------------------------------------------------------------------


async def test_get_order_triage_context_matches_the_shared_models(oms_app, wms_app, tms_app):
    from models.oms import LineItem, Order, OrderException
    from models.tms import Shipment
    from models.wms import InventoryItem

    required_keys = {"order", "line_items", "exceptions", "shipment", "inventory"}

    async with _live_services(oms_app, wms_app, tms_app) as urls:
        async with _client_session(urls) as session:
            with_shipment = await _call(
                session, "get_order_triage_context", {"order_id": "ORD-2025-001"}
            )
            without_shipment = await _call(
                session, "get_order_triage_context", {"order_id": "ORD-2025-006"}
            )

    assert with_shipment.is_error is False
    payload = _tool_payload(with_shipment)
    assert set(payload) == required_keys, f"payload keys are {sorted(payload)}"
    order = Order.model_validate(payload["order"])
    assert order.order_id == "ORD-2025-001"
    for line_item in payload["line_items"]:
        LineItem.model_validate(line_item)
    for exception in payload["exceptions"]:
        OrderException.model_validate(exception)
    for inventory_item in payload["inventory"]:
        InventoryItem.model_validate(inventory_item)
    # the shipment slot is present and, for an order that has one, populated
    assert payload["shipment"] is not None
    Shipment.model_validate(payload["shipment"])

    assert without_shipment.is_error is False
    payload_no_shipment = _tool_payload(without_shipment)
    assert set(payload_no_shipment) == required_keys
    # the slot stays in the payload, carrying null, rather than disappearing
    assert payload_no_shipment["shipment"] is None


async def test_get_order_triage_context_handles_unresolvable_orders(oms_app, wms_app, tms_app):
    order_id = await _seed_picking_status_order(oms_app)

    async with _live_services(oms_app, wms_app, tms_app) as urls:
        async with _client_session(urls) as session:
            not_found = await _call(
                session, "get_order_triage_context", {"order_id": "ORD-DOES-NOT-EXIST"}
            )
            pre_existing_500 = await _call(
                session, "get_order_triage_context", {"order_id": order_id}
            )
            # neither failure was an unhandled exception reaching the
            # transport: the same session answers a further request cleanly
            still_alive = await _list(session)

    assert not_found.is_error is True, "an unresolvable order must come back as a tool-level error"
    assert pre_existing_500.is_error is True, (
        "a row the backend cannot serialize must come back as a tool-level error, not a crash"
    )
    assert {tool.name for tool in still_alive.tools} == TOOL_NAMES


# ---------------------------------------------------------------------------
# list_stuck_orders
# ---------------------------------------------------------------------------


async def test_list_stuck_orders_matches_the_stuck_predicate_right_now(
    ops_client, oms_app, wms_app, tms_app
):
    from triage.detection import is_stuck

    def _naive(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.replace(tzinfo=None)

    orders_page = await ops_client.list_orders(limit=200)
    exceptions_page = await ops_client.list_exceptions(limit=200)
    exceptions_by_order: dict[str, list[Any]] = {}
    for exception in exceptions_page.items:
        exceptions_by_order.setdefault(exception.order_id, []).append(
            exception.model_copy(
                update={
                    "created_at": _naive(exception.created_at),
                    "resolved_at": _naive(exception.resolved_at),
                }
            )
        )

    at = datetime.now()
    expected_stuck_ids: set[str] = set()
    for order in orders_page.items:
        naive_order = order.model_copy(
            update={
                "created_at": _naive(order.created_at),
                "updated_at": _naive(order.updated_at),
                "promised_delivery_date": _naive(order.promised_delivery_date),
            }
        )
        case = SimpleNamespace(
            order=naive_order, exceptions=exceptions_by_order.get(order.order_id, [])
        )
        if is_stuck(case, at):
            expected_stuck_ids.add(order.order_id)

    # a vacuous cross-check (nothing stuck, or nothing not-stuck) would pass
    # regardless of whether the tool filters anything at all
    all_ids = {order.order_id for order in orders_page.items}
    assert expected_stuck_ids, "no order in the live fixture is stuck; the cross-check is vacuous"
    assert expected_stuck_ids < all_ids, "every fixture order is stuck; the cross-check is vacuous"

    async with _live_services(oms_app, wms_app, tms_app) as urls:
        async with _client_session(urls) as session:
            result = await _call(session, "list_stuck_orders")

    assert result.is_error is False
    actual_ids = _extract_order_ids(_tool_payload(result))
    assert actual_ids == expected_stuck_ids


async def test_list_stuck_orders_caps_its_result_size(oms_app, wms_app, tms_app):
    import mcp_server

    # the cap must be a positive integer constant on the package's own public
    # surface, not merely an internal loop bound nothing outside can see
    candidates = {
        name: getattr(mcp_server, name)
        for name in dir(mcp_server)
        if not name.startswith("_")
        and isinstance(getattr(mcp_server, name), int)
        and not isinstance(getattr(mcp_server, name), bool)
        and getattr(mcp_server, name) > 0
    }
    narrowed = {
        n: v for n, v in candidates.items() if any(w in n.lower() for w in ("cap", "limit", "max"))
    }
    if narrowed:
        candidates = narrowed
    assert candidates, (
        f"no importable positive-integer cap constant found; public ints: {candidates}"
    )
    assert len(candidates) == 1, f"the results cap is ambiguous: {sorted(candidates)}"
    cap = next(iter(candidates.values()))

    extra = cap + 50
    await _seed_bulk_stuck_orders(oms_app, extra)

    async with _live_services(oms_app, wms_app, tms_app) as urls:
        async with _client_session(urls) as session:
            result = await _call(session, "list_stuck_orders")

    assert result.is_error is False
    returned_ids = _extract_order_ids(_tool_payload(result))
    # the seeded population (the bulk rows plus the four permanently-stuck
    # fixture rows) is well past the cap, so an uncapped answer would prove it
    assert len(returned_ids) == cap, (
        f"seeded {extra + 4} stuck orders, well past the cap of {cap}, "
        f"but the tool returned {len(returned_ids)}"
    )


# ---------------------------------------------------------------------------
# Diagnosis stays out of every response
# ---------------------------------------------------------------------------


async def test_no_tool_response_carries_a_root_cause_field(oms_app, wms_app, tms_app):
    async with _live_services(oms_app, wms_app, tms_app) as urls:
        async with _client_session(urls) as session:
            context = await _call(session, "get_order_triage_context", {"order_id": "ORD-2025-001"})
            stuck = await _call(session, "list_stuck_orders")
            carriers = await _call(session, "get_carrier_stats")

    _assert_no_root_cause_leak(_tool_payload(context), "get_order_triage_context")
    _assert_no_root_cause_leak(_tool_payload(stuck), "list_stuck_orders")
    _assert_no_root_cause_leak(_tool_payload(carriers), "get_carrier_stats")


# ---------------------------------------------------------------------------
# get_carrier_stats
# ---------------------------------------------------------------------------


async def test_get_carrier_stats_is_a_pure_passthrough(oms_app, wms_app, tms_app):
    from config.settings import Settings
    from services.client import OpsClient

    async with _live_services(oms_app, wms_app, tms_app) as urls:
        reference_client = OpsClient(
            settings=Settings(
                oms_api_url=urls["OMS_API_URL"],
                wms_api_url=urls["WMS_API_URL"],
                tms_api_url=urls["TMS_API_URL"],
            )
        )
        try:
            expected = await reference_client.get_carrier_performance()
        finally:
            await reference_client.aclose()

        async with _client_session(urls) as session:
            result = await _call(session, "get_carrier_stats")

    assert result.is_error is False
    payload = _tool_payload(result)
    expected_payload = [item.model_dump(mode="json") for item in expected]
    assert payload == expected_payload, "the tool's answer diverges from the raw carrier stats call"


# ---------------------------------------------------------------------------
# Bad input is rejected without ever reaching a private function
# ---------------------------------------------------------------------------


async def test_call_tool_missing_required_argument_is_rejected_cleanly():
    mcp = _import_mcp()
    async with _client_session() as session:
        try:
            result = await _call(session, "get_order_triage_context", {})
        except mcp.MCPError:
            rejected = True
        else:
            rejected = result.is_error is True
        assert rejected, "a call missing its required argument must be refused, not accepted"

        # whichever channel carried the refusal, it was not an unhandled
        # exception that broke the transport -- the session still answers
        after = await _list(session)
    assert {tool.name for tool in after.tools} == TOOL_NAMES


# ---------------------------------------------------------------------------
# One entrypoint, non-interactive, no required arguments
# ---------------------------------------------------------------------------


async def test_entrypoint_runs_non_interactively_with_no_extra_arguments():
    # a bare `python -m mcp_server`, no subcommand, no flags; an entrypoint
    # that blocked on interactive input would time out here instead of
    # answering the handshake
    async with _client_session() as session:
        result = await _list(session)
    assert {tool.name for tool in result.tools} == TOOL_NAMES

    pyproject = _load_toml(_repo_root() / "pyproject.toml")
    scripts = pyproject.get("project", {}).get("scripts", {})
    competing = [
        name
        for name, target in scripts.items()
        if target.split(":")[0].split(".")[0] == "mcp_server"
    ]
    assert len(competing) <= 1, (
        f"more than one console-script entrypoint into mcp_server: {competing}"
    )


# ---------------------------------------------------------------------------
# Build and supply-chain bookkeeping
# ---------------------------------------------------------------------------


def test_mcp_server_is_registered_for_type_checking():
    pyproject = _load_toml(_repo_root() / "pyproject.toml")
    files = pyproject.get("tool", {}).get("mypy", {}).get("files", [])
    assert "mcp_server" in files, f"mcp_server is missing from [tool.mypy] files: {files}"


def test_mcp_dependency_pin_matches_between_pyproject_and_lockfile():
    from packaging.requirements import Requirement
    from packaging.version import Version

    pyproject = _load_toml(_repo_root() / "pyproject.toml")
    dependencies = pyproject.get("project", {}).get("dependencies", [])
    mcp_requirements = [
        req for dep in dependencies if (req := Requirement(dep)).name.lower() == "mcp"
    ]
    assert mcp_requirements, (
        "no 'mcp' entry in [project.dependencies]; the SDK the server imports "
        "is not a declared runtime dependency"
    )
    assert len(mcp_requirements) == 1, f"more than one 'mcp' dependency entry: {mcp_requirements}"
    requirement = mcp_requirements[0]

    lock = _load_toml(_repo_root() / "uv.lock")
    locked = [pkg for pkg in lock.get("package", []) if pkg.get("name") == "mcp"]
    assert locked, "uv.lock carries no 'mcp' package entry"
    assert len(locked) == 1, f"uv.lock carries more than one 'mcp' package entry: {locked}"
    locked_version = Version(locked[0]["version"])

    assert requirement.specifier.contains(locked_version, prereleases=True), (
        f"pyproject.toml pins mcp{requirement.specifier}, but uv.lock resolved "
        f"{locked_version} -- `uv sync --frozen` would disagree with a bare install"
    )


# ---------------------------------------------------------------------------
# Stdout carries only the protocol
# ---------------------------------------------------------------------------


def test_no_module_writes_raw_stdout():
    hits: list[str] = []
    root = _repo_root()
    for path in _mcp_server_modules():
        hits += _stdout_write_hits(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
    assert not hits, "a direct stdout write was found:\n" + "\n".join(hits)


async def test_stdout_never_carries_a_non_protocol_line(oms_app, wms_app, tms_app):
    mcp = _import_mcp()
    order_id = await _seed_picking_status_order(oms_app)
    transport_faults: list[Exception] = []

    async def _capture(message: Any) -> None:
        if isinstance(message, Exception):
            transport_faults.append(message)

    async with _live_services(oms_app, wms_app, tms_app) as urls:
        params = mcp.StdioServerParameters(
            command=sys.executable, args=list(SERVER_ARGS), cwd=str(_repo_root()), env=urls
        )
        async with mcp.stdio_client(params) as (read_stream, write_stream):
            async with mcp.ClientSession(
                read_stream, write_stream, message_handler=_capture
            ) as session:
                await asyncio.wait_for(session.initialize(), timeout=INIT_TIMEOUT)
                # exercise the error paths most likely to leak a raw
                # traceback onto stdout instead of a protocol-shaped message
                await _list(session)
                await _call(session, "get_order_triage_context", {"order_id": order_id})
                await _call(session, "get_order_triage_context", {"order_id": "ORD-DOES-NOT-EXIST"})
                try:
                    await _call(session, "get_order_triage_context", {})
                except mcp.MCPError:
                    pass

    assert not transport_faults, (
        "the transport surfaced a parse fault -- something on stdout was not "
        f"a valid protocol message: {transport_faults!r}"
    )

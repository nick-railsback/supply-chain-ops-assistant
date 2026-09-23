"""The MCP-facing layer: registers the three read-only tools over stdio.

The shared OpsClient is built once, at server startup, from the process's
own environment via config.settings.get_settings() -- a normal OpsClient
consumer like every other entrypoint -- and closed on shutdown, through the
SDK's lifespan hook. Every raised exception from a tool body (NotFoundError,
ServiceUnavailableError, ValidationError, a missing-argument validation
failure, or anything else) is converted by the SDK itself into a tool-level
CallToolResult(is_error=True) rather than an unhandled exception reaching
the transport -- nothing here needs to catch those exceptions itself.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from config.settings import get_settings
from mcp_server import tools
from mcp_server.models import TriageContext
from services.client import OpsClient


@asynccontextmanager
async def _lifespan(_server: MCPServer) -> AsyncIterator[OpsClient]:
    client = OpsClient(settings=get_settings())
    try:
        yield client
    finally:
        await client.aclose()


mcp = MCPServer("triage", lifespan=_lifespan)

_READ_ONLY = ToolAnnotations(read_only_hint=True)


@mcp.tool(annotations=_READ_ONLY)
async def list_stuck_orders(ctx: Context[OpsClient, Any]) -> list[str]:
    return await tools.list_stuck_orders(ctx.request_context.lifespan_context)


@mcp.tool(annotations=_READ_ONLY)
async def get_order_triage_context(order_id: str, ctx: Context[OpsClient, Any]) -> TriageContext:
    return await tools.get_order_triage_context(ctx.request_context.lifespan_context, order_id)


@mcp.tool(annotations=_READ_ONLY)
async def get_carrier_stats(ctx: Context[OpsClient, Any]) -> CallToolResult:
    # A bare list return type auto-wraps into structured content shaped
    # {"result": [...]}; the SDK's own object-schema requirement for
    # structured content. Building the CallToolResult by hand keeps this
    # tool's answer a literal top-level JSON array -- a true pass-through of
    # get_carrier_performance()'s own shape, not a second aggregation.
    stats = await tools.get_carrier_stats(ctx.request_context.lifespan_context)
    payload = [item.model_dump(mode="json") for item in stats]
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))])

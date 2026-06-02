"""Tests for the shared structured-output client."""

from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import ToolUseBlock

from agent.llm import structured_call


async def test_structured_call_closes_client():
    """The per-call AsyncAnthropic client is closed, even on the happy path.

    Regression: leaving it open leaks an httpx AsyncClient per call, which then
    fails to tear down ("Event loop is closed") and spams the eval output.
    """
    block = ToolUseBlock(type="tool_use", id="t1", name="emit", input={"ok": True})
    message = MagicMock()
    message.content = [block]
    message.usage = MagicMock(input_tokens=10, output_tokens=5)

    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=message)

    with patch("agent.llm._client", return_value=client):
        data, usage = await structured_call(
            system="s",
            user="u",
            tool_name="emit",
            tool_description="d",
            input_schema={"type": "object"},
        )

    assert data == {"ok": True}
    assert usage == {"input_tokens": 10, "output_tokens": 5}
    client.close.assert_awaited_once()


async def test_structured_call_closes_client_on_error():
    """The client is closed even when no matching tool_use block comes back."""
    message = MagicMock()
    message.content = []  # no tool_use block -> structured_call raises
    message.usage = MagicMock(input_tokens=1, output_tokens=1)

    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=message)

    with patch("agent.llm._client", return_value=client):
        raised = False
        try:
            await structured_call(
                system="s",
                user="u",
                tool_name="emit",
                tool_description="d",
                input_schema={"type": "object"},
            )
        except ValueError:
            raised = True

    assert raised
    client.close.assert_awaited_once()

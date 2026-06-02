"""Shared Claude client for structured-output (tool-use) calls.

Centralizes the *one correct way* to get schema-valid structure out of the
model. Forced ``tool_choice`` means the model returns arguments matching the
tool's ``input_schema`` by construction — there is no free-text JSON to parse,
which removes the entire class of "model wrapped JSON in a code fence" failures
that the previous ``model_validate_json(content[0].text)`` path swallowed.

The ``anthropic`` import is deferred to call time: the module loads without the
package installed, and any caller falls back gracefully via ``LLMUnavailable``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from config.settings import get_settings

if TYPE_CHECKING:  # for type checkers only; not imported at runtime
    import anthropic
    from anthropic.types import (
        CacheControlEphemeralParam,
        MessageParam,
        TextBlockParam,
        ToolChoiceToolParam,
        ToolParam,
    )

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """Raised when the LLM cannot be used (no key, disabled, or SDK missing).

    Callers treat this as a signal to fall back to the rule-based path rather
    than as a hard error.
    """


def _client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    if not settings.is_llm_available:
        raise LLMUnavailable("ANTHROPIC_API_KEY not set or LLM disabled")
    try:
        import anthropic
    except ModuleNotFoundError as exc:  # dependency declared but not installed
        raise LLMUnavailable("anthropic SDK is not installed") from exc
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def structured_call(
    *,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
    max_tokens: int = 1024,
    temperature: float = 0.0,  # deterministic interpretation
    cache_system: bool = True,  # cache the large, identical-every-call static block
) -> tuple[dict[str, Any], dict[str, int]]:
    """Call Claude with a single forced tool; return ``(tool_input, usage)``.

    Returns the tool_use ``input`` dict (schema-valid by construction) plus a
    token-usage dict so callers can log cost/latency. Raises ``LLMUnavailable``
    when no key/SDK is configured, or ``ValueError`` if the model somehow
    returns no matching tool_use block.
    """
    settings = get_settings()
    client = _client()
    import anthropic  # _client() has already verified the SDK is importable

    # cache_control on the (large, identical-every-call) system + tool block.
    text_block: TextBlockParam = {"type": "text", "text": system}
    tool: ToolParam = cast(
        "ToolParam",
        {
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
        },
    )
    if cache_system:
        cache: CacheControlEphemeralParam = {"type": "ephemeral"}
        text_block["cache_control"] = cache
        tool["cache_control"] = cache

    tool_choice: ToolChoiceToolParam = {"type": "tool", "name": tool_name}  # forced
    messages: list[MessageParam] = [{"role": "user", "content": user}]

    message = await client.messages.create(
        model=settings.llm_model,
        system=[text_block],
        tools=[tool],
        tool_choice=tool_choice,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=messages,
    )

    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }

    for block in message.content:
        if isinstance(block, anthropic.types.ToolUseBlock) and block.name == tool_name:
            logger.debug("structured_call %s ok usage=%s", tool_name, usage)
            return cast("dict[str, Any]", block.input), usage

    raise ValueError(f"Model did not return a '{tool_name}' tool_use block")

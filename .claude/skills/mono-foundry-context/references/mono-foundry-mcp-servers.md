# monō foundry — MCP servers

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary file: `docs/mcp.md` (content-hash `81e4d3a3`); supporting `docs/security.md` (`c12add0b`)

## Contents

- [What MCP gives you here](#what-mcp-gives-you-here)
- [Config discovery and precedence](#config-discovery-and-precedence)
- [Three config formats](#three-config-formats)
- [Server fields](#server-fields)
- [stdio only — SSE is not supported](#stdio-only--sse-is-not-supported)
- [Lifecycle and timeouts](#lifecycle-and-timeouts)
- [Security position](#security-position)

## What MCP gives you here

MCP servers are local processes exposing tools over the Model Context Protocol. The CLI discovers configs, connects on demand, and exposes their tools to the agent. — [docs/mcp.md#L26](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L26)

Exactly two tools are registered for the agent: `list_mcp_servers` discovers and lists configured servers with status, transport, and available tools; `call_mcp_tool` calls a specific tool on a specific server. — [docs/mcp.md#L30](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L30)

This is the **user-scoped capability escape hatch** in an otherwise fixed tool registry. The registry is compiled in at build time and the agent cannot run arbitrary executables — but `call_mcp_tool` reaches any stdio process you configure, which is precisely why the docs treat MCP as the one exception to "no outbound calls from tool execution". — [docs/security.md#L81](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L81)

Discovery is stateless and re-run on demand, with no file watchers and no background processes until a tool is actually called — the same posture as skill discovery. — [docs/mcp.md#L33](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L33)

## Config discovery and precedence

Eight locations are scanned in a fixed order and **the first file to define a server name wins**; workspace configs precede home configs. — [docs/mcp.md#L39](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L39)

| # | Location | Format | Scope |
|---|---|---|---|
| 1 | `<workspace>/.mcp.json` | `servers` | Workspace |
| 2 | `<workspace>/.claude/mcp.json` | `servers` | Workspace |
| 3 | `<workspace>/.vscode/mcp.json` | `servers` | Workspace |
| 4 | `~/.monofoundry/mcp.json` | `servers` | Home |
| 5 | `~/.mcp.json` | `servers` | Home |
| 6 | `~/.claude/mcp.json` | `servers` | Home |
| 7 | `~/.vscode/settings.json` | `vscodeSettings` | Home |
| 8 | `~/.gemini/antigravity/mcp_config.json` | `mcpServers` | Home |

— [docs/mcp.md#L41](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L41)

Note that `~/.monofoundry/mcp.json` sits at position 4 — **below all three workspace paths but above the other home paths**. A workspace `.claude/mcp.json` therefore beats your primary home config, which is the intended workspace-wins behaviour but can surprise when debugging why a server is not the one you configured. — [docs/mcp.md#L46](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L46)

The docs also flag a subtlety that matters when hand-editing: **format is determined by the file's location, not by its content.** Putting an `mcpServers` block in `.mcp.json` will not work, because that path is parsed as `servers`. — [docs/mcp.md#L58](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L58)

## Three config formats

The recommended `servers` format is the VS Code native shape, used by `.mcp.json`, `.claude/mcp.json`, and `~/.monofoundry/mcp.json`. — [docs/mcp.md#L60](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L60)

```json
{
  "servers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/projects"],
      "env": {}
    }
  }
}
```

The legacy `mcpServers` format is used only by `~/.gemini/antigravity/mcp_config.json`, and differs by using `serverUrl` instead of `url` and `disabled` instead of `enabled` — an inversion worth catching when porting a config across. — [docs/mcp.md#L85](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L85)

The VS Code `settings.json` form nests servers under the `"mcp.servers"` key. — [docs/mcp.md#L104](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L104)

All config files accept **JSONC** — `//` line comments and trailing commas are stripped, with automatic fallback to JSONC parsing when strict JSON fails. — [docs/mcp.md#L170](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L170)

## Server fields

Supported fields are `type`, `command`, `args`, `env`, `cwd`, `url`, and `enabled`. — [docs/mcp.md#L126](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L126)

Two behaviours are easy to miss. `env` is **merged with the current process environment**, with config values overriding existing ones — so a server inherits your shell environment rather than starting clean. And `cwd` is resolved relative to the config file's directory, defaulting to that directory, not to the workspace root. — [docs/mcp.md#L131](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L131)

On Windows the `command` is spawned with `shell: true` so `npx` and similar wrappers resolve correctly. — [docs/mcp.md#L136](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L136)

## stdio only — SSE is not supported

Only stdio transport works. The CLI spawns the server process, speaks JSON-RPC 2.0 over stdin/stdout, and performs the standard MCP `initialize` handshake at protocol version `2024-11-05`. — [docs/mcp.md#L142](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L142)

SSE is explicitly **not** supported: a config specifying `type: "sse"` or carrying a `url`/`serverUrl` appears in listings with an error status of `"SSE transport not supported"` and its tool calls fail. Since transport is auto-detected as SSE whenever a `url` is present, an accidentally-copied `url` field silently disables a server. — [docs/mcp.md#L144](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L144)

This is a real constraint when integrating a client's existing MCP estate — remote/hosted MCP servers cannot be pointed at directly and need a local stdio bridge process. — [docs/mcp.md#L133](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L133)

## Lifecycle and timeouts

Connection is **lazy**: no server starts when the CLI launches; a process is spawned only when the agent first calls a tool on it. — [docs/mcp.md#L151](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L151)

After connecting, the server's `tools/list` result is cached for the session — so a server that gains tools mid-session will not surface them until restart. — [docs/mcp.md#L152](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L152)

Each JSON-RPC request carries a **30-second timeout**, which sits inside the 60-second per-tool watchdog described in `mono-foundry-security-model.md` — so a slow MCP server fails at 30s, not 60s. — [docs/mcp.md#L153](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L153)

All spawned server processes are killed when the CLI exits and are `unref`'d so they never prevent a clean exit. — [docs/mcp.md#L154](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L154)

Connection failures include the command and arguments in the error message, which makes missing-executable and wrong-path diagnosis fast. — [docs/mcp.md#L156](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L156)

## Security position

`call_mcp_tool` is classified as a **mutating** tool, so it is intercepted by approval mode, and a brief summary of the server and tool name is displayed before execution even when approval mode is off. — [docs/mcp.md#L162](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L162)

The trust statement is explicit: MCP servers run with the user's permissions and can make their own network calls, and the CLI does not configure, contact, or trust any MCP server by default. — [docs/security.md#L206](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L206)

Accordingly the hardening guidance names MCP server review as its own line item — audit configs before adding them, because they run with your permissions. — [docs/security.md#L287](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L287)

Since v0.22.0, MCP **server spawning** is additionally gated behind workspace consent, which is a separate gate from the per-call approval prompt. — [CHANGELOG.md#L126](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L126)

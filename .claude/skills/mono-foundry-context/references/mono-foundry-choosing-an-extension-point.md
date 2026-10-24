# monō foundry — choosing an extension point

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Synthesised across `docs/skills.md` (`191c95f3`), `docs/mcp.md` (`81e4d3a3`), `docs/plugins.md` (`f1cb1ea7`), `docs/security.md` (`c12add0b`)

If you are building something *on* monō foundry rather than *with* it, the first decision is which of four surfaces to use. They are not interchangeable, and picking wrong costs a rewrite. This reference is the decision itself; the per-surface references carry the detail.

## Contents

- [The four surfaces](#the-four-surfaces)
- [Decision matrix](#decision-matrix)
- [What none of them can do](#what-none-of-them-can-do)
- [Constraints that shape a build](#constraints-that-shape-a-build)
- [A realistic starter shape](#a-realistic-starter-shape)

## The four surfaces

**Agent instruction files** are ambient project context loaded every turn from `MONOFOUNDRY.md` or a fallback such as `CLAUDE.md` or `AGENTS.md`. Zero-effort, always-on, and therefore always paying token cost. — [docs/index.md#L50](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/index.md#L50)

**Skills** are markdown instruction sets discovered from twelve directories and invoked on demand by the agent's `invoke_skill` tool or a `/<skill-name>` command. They add *guidance*, never capability. — [docs/skills.md#L28](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L28)

**MCP servers** are local stdio processes exposing tools the agent reaches through `call_mcp_tool`. This is the user-scoped way to add genuinely new capability without shipping a plugin. — [docs/mcp.md#L26](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L26)

**Plugins** are installable packages with a manifest, a permission array, and an isolated child-process runtime. They alone can register or **override built-in tools**, add slash commands, provide LSP, highlighters, and themes. — [docs/plugins.md#L49](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L49)

## Decision matrix

| You need to… | Surface | Why |
|---|---|---|
| Encode project conventions the agent should always know | Instruction file | Loaded every turn, no invocation needed |
| Encode a repeatable procedure the agent invokes when relevant | Skill | On-demand body load; only the description is standing cost |
| Give the agent a new tool that talks to your system | MCP server | Stdio process, no packaging, user-scoped |
| Replace a built-in tool with a better implementation | Plugin | `tool:override:<name>` is plugin-only |
| Add a `/command` to the REPL | Plugin | `command:provide:<name>`; skills only get `/<skill-name>` |
| Ship it to other people with versioning and integrity checks | Plugin | Lockfile, SHA-256, GitHub release install |
| Change how output looks | Plugin | `highlighter:provide` / `theme:provide` |

The permission vocabulary is what makes the plugin/MCP line concrete: only a plugin can declare `tool:override:<name>`, and only a plugin's capabilities are gated and displayed before enabling. — [docs/plugins.md#L390](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L390)

Conversely, MCP wins on iteration speed: no manifest, no install step, no restart-to-reload, and discovery is re-run on every `list_mcp_servers` or `call_mcp_tool` invocation. — [docs/mcp.md#L150](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L150)

Plugins have no live unload — disabling or removing one needs a session or daemon restart before its commands disappear — which makes the edit-test loop meaningfully slower than MCP's. — [docs/plugins.md#L441](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L441)

## What none of them can do

**Change the agent loop.** Orchestration, tool selection, and planning are server-side, and the CLI is a passive executor of the backend's decisions. No local extension point intercepts that. — [docs/security.md#L118](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L118)

**Request a subagent.** Spawning is decided by the backend orchestrator; the CLI cannot ask for one, so you cannot build a fan-out pattern client-side. — [docs/subagents.md#L141](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L141)

**Restrict the agent's tools.** A skill's `tools` field is informational and does not restrict what the agent may call, so it is not an allowlist mechanism. — [docs/skills.md#L95](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L95)

**Auto-trigger on context.** `trigger` documents only `manual`, so a skill fires when the agent chooses to invoke it or the user types the command — there is no documented event or pattern trigger. — [docs/skills.md#L97](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L97)

**Run hooks on lifecycle events.** Nothing in the documented surface corresponds to pre/post tool-use hooks; the approval gate is the only interception point, and it is user-interactive rather than programmable. — [docs/security.md#L165](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L165)

## Constraints that shape a build

**Plugin runtime is Bun, not Node.** Standalone binaries use an embedded Bun runtime and do not guarantee a stock Node.js; avoid Node-only built-ins, a separately installed `node`, and the ESM `__dirname` global. Use `new URL("./asset", import.meta.url)` with `fileURLToPath()` for asset paths. — [docs/plugins.md#L43](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L43)

**MCP is stdio-only.** SSE is unsupported, and transport auto-detects to SSE whenever a `url` or `serverUrl` is present — so a stray `url` field silently breaks a server. Remote MCP services need a local bridge process. — [docs/mcp.md#L144](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L144)

**MCP requests time out at 30 seconds**, inside the 60-second per-tool watchdog — so long-running work needs an async job pattern with a polling tool, not a blocking call. — [docs/mcp.md#L153](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L153)

**MCP tool lists are cached per session**, so a server that gains tools at runtime will not surface them until the session restarts — declare your full tool surface up front. — [docs/mcp.md#L152](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L152)

**Plugin config schemas support a JSON Schema subset only** — `type`, `enum`, `const`, numeric bounds, string length and `pattern`, `items`, `properties`, `required`. No `oneOf`, `anyOf`, or `$ref`, so keep config shapes flat and simple. — [docs/plugins.md#L252](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L252)

**Skill descriptions are a standing per-turn cost.** Every discovered skill's name, first description line, and source label go into the workspace context at the start of each turn, while bodies load on demand — so many skills with long descriptions is the expensive shape. — [docs/skills.md#L157](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L157)

**Name collisions fail silently.** A skill whose slug matches a built-in command is simply not registered as a slash command, with no error — check `/skills` output rather than assuming. — [docs/skills.md#L172](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L172)

## A realistic starter shape

For a project meant to demonstrate range in a short window, the highest signal-per-hour combination is a **skill plus an MCP server**: the skill encodes the workflow and the MCP server supplies the capability the workflow needs, with neither requiring a build pipeline, a manifest, or a restart loop. — [docs/mcp.md#L189](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L189)

Register the server at `<workspace>/.mcp.json` so it is workspace-scoped and travels with the repo, remembering that `cwd` resolves relative to the config file's directory rather than the workspace root. — [docs/mcp.md#L191](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/mcp.md#L191)

Put the skill at `<workspace>/.monofoundry/skills/<name>/SKILL.md` — first in workspace scan order, so it wins any collision with a `.claude/` or `.cursor/` equivalent already in the repo. — [docs/skills.md#L38](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L38)

Reach for a plugin only if the demonstration genuinely needs a tool override, a slash command, or distributable packaging — those three are the only things that justify the manifest, the permission array, the Bun constraint, and the restart loop. — [docs/plugins.md#L32](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L32)

Scaffold project instructions with `/init`, which detects name, package manager, frameworks, languages, and scripts, then fill the deliberately-empty `## Architecture` and `## Conventions` sections yourself. — [docs/commands.md#L207](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L207)

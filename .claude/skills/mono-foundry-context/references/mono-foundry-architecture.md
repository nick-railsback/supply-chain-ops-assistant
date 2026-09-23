# monō foundry — thin-client architecture

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary files: `README.md` (content-hash `82d6f7b4`), `docs/index.md` (`77dfbfb3`), `docs/security.md` (`c12add0b`), `docs/daemon.md` (`ba6dce0b`)

## Contents

- [The inversion](#the-inversion)
- [What runs where](#what-runs-where)
- [The three-process picture](#the-three-process-picture)
- [Why the inversion is the product](#why-the-inversion-is-the-product)
- [Consequences you can reason from](#consequences-you-can-reason-from)
- [Config surface](#config-surface)

## The inversion

monō foundry is a **thin-client CLI** for the monō ai coding agent: the agent loop, model intelligence, and projects/workspaces run server-side, while the local daemon hosts the CLI runtime, streams responses, and executes tool commands in your local context. — [README.md#L3](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L3)

This is the single load-bearing design decision, and almost every other property in this contextualizer follows from it. Most coding-agent harnesses put the loop on the client: the CLI holds the conversation, decides which tool to call next, and talks to a model API. monō foundry moves that decision-making to the backend and leaves the client as an executor. — [docs/security.md#L42](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L42)

The docs state the consequence bluntly: the CLI and daemon **never** choose tools themselves — they are passive executors of the backend's decisions. — [docs/security.md#L118](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L118)

## What runs where

| Concern | Location | Evidence |
|---|---|---|
| Agent loop, tool selection, orchestration | Backend (`core.monoai.co`) | [security.md#L42](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L42) |
| Model intelligence / inference | Backend | [README.md#L3](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L3) |
| Web search, URL fetch, external lookups | Backend, screened by SafeLinks | [security.md#L218](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L218) |
| Subagent spawn decisions | Backend orchestrator | [subagents.md#L22](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L22) |
| RBAC, org/project/work-item scoping | Backend | [security.md#L182](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L182) |
| Tool **execution** (files, terminal, git, MCP) | Local, as the running user | [security.md#L143](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L143) |
| Skill / MCP / instruction discovery | Local, stateless re-scan | [skills.md#L26](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L26) |
| Conversation history | Local, plus backend unless `/nosave` | [README.md#L102](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L102) |
| Plugin host | Local, isolated child process | [plugins.md#L36](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L36) |

## The three-process picture

In default mode there are three participants, not two. The foreground CLI is the frontend; the local daemon hosts the control loop, the Core stream, local tool execution, subagent lifecycle, and bridge/session state; the backend runs the agent. — [docs/daemon.md#L3](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L3)

The wire protocol is server-sent events carrying `ide_automation_command` events that name a tool; the client executes it locally and posts the result back. In daemon mode the daemon owns that round-trip and the CLI attaches over loopback. — [docs/security.md#L118](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L118)

Direct mode (`--direct`, `--no-daemon`, `MONOFOUNDRY_NO_DAEMON=1`) collapses this to two participants by cutting the daemon out, and is positioned as the recovery/debugging escape hatch rather than a normal operating mode. — [docs/daemon.md#L75](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L75)

## Why the inversion is the product

The thin client is what lets monō ai sell a *platform* rather than a CLI. Because orchestration is server-side, every turn is subject to backend RBAC, organisation scoping, and audit — the CLI has no way to access resources the backend does not authorise. — [docs/security.md#L188](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L188)

It also means capability upgrades ship without a client release. New models, better orchestration, and new platform connections land server-side; the local binary only needs to keep executing the same fixed tool registry. That registry is compiled in at build time and the agent cannot instruct the CLI to run anything outside it. — [docs/security.md#L124](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L124)

The flip side is the honest trade: the client cannot function offline, cannot swap in a local model, and cannot decide to spawn its own subagent — the CLI cannot request a subagent directly. — [docs/subagents.md#L141](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L141)

## Consequences you can reason from

**Prompt-injection defence moves off the client.** Because the backend performs all external lookups behind SafeLinks host screening, an injection that tries to point the agent at attacker infrastructure is stopped server-side before any request reaches the target. The client never needs local URL screening. — [docs/security.md#L220](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L220)

**The local trust boundary is the user account, not a sandbox.** Tools run with exactly the permissions of the user running the CLI — no privilege escalation, no remote sandbox, no isolation. The daemon changes *where* the runtime is hosted, not *what* permissions local tools have. — [docs/daemon.md#L167](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L167)

**Data minimisation is structural, not policy.** Text files are never uploaded; the agent reads them locally through `read_file` and only the tool result crosses the wire. Binary attachments are the sole upload path, capped at 20 MB. — [docs/security.md#L272](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L272)

**There is no telemetry.** The CLI does not collect, transmit, or store analytics or usage telemetry, and does not phone home. For a regulated client this is a short, checkable claim rather than a policy promise. — [docs/security.md#L250](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L250)

## Config surface

Everything user-configurable lives under `~/.monofoundry/`, with `config.json` holding credentials and settings, and a documented fallback chain that reads other tools' config locations. — [docs/index.md#L20](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/index.md#L20)

Workspace-level config always takes precedence over home-level config — a single precedence rule that holds across skills, MCP servers, agent instructions, and plugin enablement. — [docs/index.md#L52](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/index.md#L52)

Only two general user settings are documented in `config.json`: `defaultInputMode` (`"interrupt"` default, or `"clarify"` to steer the running turn) and `showIdleInputHints` (default `true`). — [docs/index.md#L32](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/index.md#L32)

Distribution is a self-contained single-file binary installed from GitHub Releases into `~/.local/bin` by default, with SHA-256 checksum verification against a published `SHASUMS256.txt` before the binary is moved into place. — [install.sh#L76](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/install.sh#L76)

On macOS the installer clears the `com.apple.quarantine` extended attribute because the binary is only ad-hoc signed — worth knowing before a client's endpoint-security team asks why. — [install.sh#L110](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/install.sh#L110)

## Where to go next

For the runtime that hosts the loop locally, read `mono-foundry-daemon-runtime.md`. For the extension surfaces you would build on, read `mono-foundry-skills-and-instructions.md`, `mono-foundry-mcp-servers.md`, and `mono-foundry-plugins.md`. For the trust story a client will interrogate, read `mono-foundry-security-model.md` — and read `mono-foundry-doc-drift.md` before quoting any approval-gate behaviour, because two guides are stale on exactly that point.

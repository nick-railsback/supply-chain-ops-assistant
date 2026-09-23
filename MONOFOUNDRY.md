# supply-chain-ops-assistant

A natural-language ops copilot over mock OMS, WMS, and TMS services. The
turn pipeline interprets a user's request, resolves it against filter and
validator registries, and enforces mutation-safety gates before any state
change reaches a backend.

## Triage wedge

Alongside the open-ended copilot, this workspace adds a bounded triage
workflow: diagnose a stuck order, propose the next action, and draft
approval-ready customer comms, reading through a dedicated read-only MCP
server rather than the general-purpose turn pipeline. See the `triage`
skill at `.monofoundry/skills/triage/SKILL.md` for the procedure, and
`.mcp.json` for the server registration.

The triage server is read-only end to end: it exposes no write path, so
every proposed action or comms draft this workflow produces needs explicit
human approval before anything is sent or executed. This workspace's
artifacts are validated against the documented monō foundry contract at the
pinned commit, not against a live monō foundry session.

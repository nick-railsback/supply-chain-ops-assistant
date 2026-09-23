---
name: mono-foundry-context
description: "Answers questions about monō foundry — monō ai's thin-client coding-agent CLI: its server-side agent loop, daemon runtime, skills/MCP/plugin extension surfaces, subagents, security model, and release history. Use when working with monofoundry, monō ai, or comparing agentic CLI harness architectures."
---

# monō foundry context navigator

## Overview

This navigator catalogs references for `monoai-labs/mono-foundry`, the thin-client CLI for the monō ai coding agent. The navigator stays small; references load only when relevant.

The one fact that explains most others: **the agent loop, model intelligence, tool selection, and orchestration run server-side. The CLI and its local daemon are passive executors.** Most surprising behaviour in this product follows from that inversion.

When asked a question this navigator's domain covers:

1. Scan the **Catalog** for the matching topic.
2. Follow the link and read that reference.
3. If the question spans several references, consult the **Cross-reference map**.
4. Follow a source permalink only when the reference itself did not answer the question.

## Critical rule — verify before quoting behaviour

The upstream repository ships **documentation only, with no source code**, and its guides carry no version stamps while its changelog is dated and semver-tagged. Four documented behaviours are contradicted by later changelog entries.

**Before making any claim about approval mode, terminal-tool gating, or subagent gating, read the `mono-foundry-doc-drift.md` reference listed in the Catalog below.** State the documented behaviour, name the changelog entry that supersedes it, and flag it as needing verification against a live build. Do not present a stale guide claim as current behaviour.

## Claims policy

Cite by default, and make load-bearing claims verifiable:

1. **Inline-cite every load-bearing claim with its SHA-pinned permalink** — the `https://github.com/monoai-labs/mono-foundry/blob/<sha>/<path>#L<start>` link the reference gives for that fact (versions, defaults, flags, tool names, behaviour a user could get wrong by guessing). Put the permalink inline, on the claim.
2. Don't cite orientational prose — *"what is monō foundry?"* — answer those from this navigator alone.
3. End with a one-line italic provenance footer: `*References consulted: foo.md, bar.md. Grounded in {{LIBRARY}}@{{VERSION}} — [reference index]({{INDEX_URL}}).*`
4. If no reference was opened, say so in the footer — never fake it.

The voice is competent and careful — no hedging.

## Catalog

| Reference | Description |
|---|---|
| [mono-foundry-architecture.md](references/mono-foundry-architecture.md) | The thin-client inversion: what runs server-side vs locally, the three-process picture, trust boundary, and the consequences that follow. **Start here.** |
| [mono-foundry-daemon-runtime.md](references/mono-foundry-daemon-runtime.md) | Daemon lifecycle, idle-shutdown asymmetry, sid/cwd session isolation, direct vs explicit-daemon modes, stale daemons, troubleshooting matrix. |
| [mono-foundry-skills-and-instructions.md](references/mono-foundry-skills-and-instructions.md) | SKILL.md format and the 12-directory discovery order; `MONOFOUNDRY.md` and its fallback chain; the multi-ecosystem compatibility bet. |
| [mono-foundry-mcp-servers.md](references/mono-foundry-mcp-servers.md) | MCP config discovery and precedence, three config formats, stdio-only constraint, lazy connection, 30-second timeout, security position. |
| [mono-foundry-plugins.md](references/mono-foundry-plugins.md) | Manifest, 15-permission vocabulary, Bun-runtime constraint, install sources and IDs, config schema subset, storage, restart semantics, first-party plugins. |
| [mono-foundry-first-party-plugins.md](references/mono-foundry-first-party-plugins.md) | The LSP, theme, and highlight plugin repos: per-plugin version floors, language and platform support, and four install/licence defects the hub docs miss. |
| [mono-foundry-subagents.md](references/mono-foundry-subagents.md) | Backend-orchestrated child conversations: lifecycle, attribution, the approval gap, persistence limits, prompting for parallelism, constraints. |
| [mono-foundry-security-model.md](references/mono-foundry-security-model.md) | Network endpoint enumeration, AES-256-GCM credential encryption and its threat model, fixed tool registry, approval mode, RBAC, hardening. |
| [mono-foundry-cli-operations.md](references/mono-foundry-cli-operations.md) | Flags, slash-command families, mid-turn steering, project/work-item binding, attachments, shell mode, cost reporting, keybindings. |
| [mono-foundry-choosing-an-extension-point.md](references/mono-foundry-choosing-an-extension-point.md) | Decision matrix across instructions / skills / MCP / plugins, what none of them can do, and the constraints that shape a build. |
| [mono-foundry-doc-drift.md](references/mono-foundry-doc-drift.md) | The four documentation defects: two stale approval-gate claims, a committed merge-conflict marker, an undocumented `/utility` command. |
| [mono-foundry-release-trajectory.md](references/mono-foundry-release-trajectory.md) | Six phases across v0.3.0 → v0.26.5 in eight weeks, what each bet cost, and what the absences imply. |

## Cross-reference map

**"How does monō foundry work?"** → `architecture`, then `daemon-runtime` for the local half.

**"How do I extend it / what should I build?"** → `choosing-an-extension-point` first, then the specific surface: `skills-and-instructions`, `mcp-servers`, or `plugins`.

**"Which first-party plugin, and what version do I need?"** → `first-party-plugins`, not the hub's plugin docs — they understate every version floor. All three together need ≥ 0.24.1.

**"Is it safe / what would a security review find?"** → `security-model`, then `doc-drift` for the two stale approval claims, then `plugins` for the permission vocabulary, `mcp-servers` for the one network exception, and `first-party-plugins` for the theme plugin's README/LICENSE contradiction.

**"Why is approval mode not stopping X?"** → `doc-drift` before `security-model`. The guides and changelog disagree; the changelog is newer.

**"Where is the product heading / how mature is it?"** → `release-trajectory`, then `doc-drift` for what fast cadence costs in documentation accuracy.

**"Something is broken."** → `daemon-runtime` troubleshooting matrix first (most operational failures are daemon-shaped), then `cli-operations`.

**Anything about parallel work, concurrency, or fan-out** → `subagents`, noting that spawning is backend-decided and cannot be requested.

## Markdown style for generated references

Reference files use **soft wrapping**: one paragraph per line, no hard line breaks at fixed column widths. Code blocks, tables, bullet lists, and headings follow their own rules; this applies to prose paragraphs only.

## Instructions to Claude

When loading a reference file, the path syntax depends on the platform:

* **Claude Code**: `Read $CLAUDE_SKILL_DIR/references/<name>.md`
* **Claude Desktop**: `Read references/<name>.md`

Loading rules:

* Load one reference at a time unless the Cross-reference map says to load both.
* If the primary reference doesn't fully answer the question, follow its source permalinks for detail.
* Do not eagerly load companion files.
* If the question is clearly out of scope for monō foundry, don't invoke this skill at all.

## Progressive disclosure

References prioritise curated insight over re-specifying upstream docs:

* **Gotchas, cross-document contradictions, and "why" context** are kept in the reference — that is the curation value, and much of it exists nowhere upstream.
* **Exhaustive flag tables, keybinding lists, and permission enumerations** are summarised and linked to their SHA-pinned source.

Every reference pins its sources by commit SHA with per-file content hashes, so a reviewer can verify any claim against the exact bytes read.

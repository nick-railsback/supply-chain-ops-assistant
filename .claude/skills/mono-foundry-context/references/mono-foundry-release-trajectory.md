# monō foundry — release trajectory

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary file: `CHANGELOG.md` (content-hash `d15d6afd`), covering v0.3.0 (2026-06-12) through v0.26.5 (2026-08-05)

## Contents

- [Cadence](#cadence)
- [Phase 1 — terminal fundamentals](#phase-1--terminal-fundamentals)
- [Phase 2 — platform integration](#phase-2--platform-integration)
- [Phase 3 — the daemon pivot](#phase-3--the-daemon-pivot)
- [Phase 4 — the plugin platform](#phase-4--the-plugin-platform)
- [Phase 5 — security hardening](#phase-5--security-hardening)
- [Phase 6 — cost transparency and polish](#phase-6--cost-transparency-and-polish)
- [What the trajectory implies](#what-the-trajectory-implies)

## Cadence

Roughly eight weeks separate v0.3.0 on 2026-06-12 from v0.26.5 on 2026-08-05 — twenty-four minor versions and many patches, which is an extremely fast release cadence. — [CHANGELOG.md#L432](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L432)

Several days carry multiple releases — v0.25.1 through v0.25.3 all land on 2026-07-16 — indicating same-day patch turnaround on release-blocking defects rather than batched releases. — [CHANGELOG.md#L49](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L49)

Entries are written in user-facing outcome language ("More reliable large-file reads") rather than commit summaries, and almost every release closes with "Bug fixes and internal improvements" — a deliberately non-exhaustive changelog. — [CHANGELOG.md#L27](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L27)

## Phase 1 — terminal fundamentals

The earliest entries are about being a competent terminal program at all: v0.3.0 moved to self-contained native binaries across macOS, Linux, and Windows on x64 and ARM64, added `--version`, and introduced fuzzy filtering in pickers. — [CHANGELOG.md#L434](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L434)

v0.4.0 is the densest early release: shell mode (`!`), `Ctrl-R` history search, `@`-path completion, the prompt stash, token tracking with `/tokens`, managed terminal tools, `run_task` discovery from npm/pnpm/bun/yarn/`.vscode/tasks.json`/Makefile, real `get_diagnostics` checkers (tsc/tsgo, oxlint, eslint, pyright, mypy), and `code_runner`. — [CHANGELOG.md#L412](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L412)

A recurring thread from here to the head of the changelog is terminal-rendering correctness — CJK and emoji width, variation selectors, wrapping, cursor drift on non-ASCII paths. This is unglamorous work that appears in at least eight separate releases. — [CHANGELOG.md#L216](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L216)

## Phase 2 — platform integration

v0.6.0 brought auth into the REPL with `/login`, `/logout`, `/status`, plus `/org` for multi-organisation users and atomic config writes. — [CHANGELOG.md#L389](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L389)

v0.9.0 added local MCP server discovery and tool invocation, and v0.10.0 added `/workitem create` — the point where the CLI starts writing to the platform, not just reading from it. — [CHANGELOG.md#L360](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L360)

v0.11.0 is the context-engineering release: external editor support, `/init` to scaffold `MONOFOUNDRY.md`, multi-format instruction files with priority fallback, and the first comprehensive security documentation. — [CHANGELOG.md#L340](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L340)

v0.12.0 introduced subagent spawning with independent tool routing and visual attribution, alongside automatic stream recovery with SSE event-ID tracking and exponential backoff. — [CHANGELOG.md#L332](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L332)

## Phase 3 — the daemon pivot

v0.15.0 is the largest architectural change in the log: the daemon runtime became the **default** for interactive sessions, with auto-start, idle shutdown, and graceful fallback to direct mode, plus `monofoundry daemon` and `monofoundry doctor`. — [CHANGELOG.md#L278](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L278)

The follow-on patches show the cost of that pivot: v0.15.1 through v0.16.2 are dominated by daemon-mode parity bugs — approval-prompt ordering in daemon sessions, home-relative path expansion, reconnection and approval consistency across direct and daemon modes. — [CHANGELOG.md#L219](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L219)

v0.15.3 addressed a subtle multi-session problem worth remembering: organisation, model, and utility selections are now isolated per session so concurrent sessions stop overwriting each other's persisted defaults. — [CHANGELOG.md#L250](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L250)

## Phase 4 — the plugin platform

v0.17.0 shipped the plugin system — install, list, enable, disable, remove, inspect from GitHub releases, URLs, or local directories, with tool provision and override. — [CHANGELOG.md#L198](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L198)

v0.18.0 and v0.18.1 built it out fast: syntax highlighting via plugins, `plugin update` and `plugin config` with schema validation, plugin-registered slash commands and child-process spawning, capability-based language-server discovery, then the isolated plugin host with managed activation, health monitoring, and bounded restarts. — [CHANGELOG.md#L186](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L186)

v0.19.0 added the token-based theming system with `/theme`, two bundled themes as editable JSON, and plugin-contributed themes behind a dedicated permission gate. — [CHANGELOG.md#L160](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L160)

The pattern across v0.17–v0.19 is worth naming: a capability ships, then within one or two releases it grows a permission gate, a config schema, and process isolation. Extension points are hardened almost as fast as they are added. — [CHANGELOG.md#L179](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L179)

## Phase 5 — security hardening

v0.22.0 is the security release: terminal and task tools gated behind approval mode, subagent calls routed through the parent's approval gate, symlink-aware workspace containment for file/search/terminal tools, sensitive environment variables stripped from spawned children, plugin lifecycle hooks requiring consent, and MCP spawning gated behind workspace consent. — [CHANGELOG.md#L123](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L123)

It also fixed a data-corruption bug that is a good reminder of what "internal improvements" can conceal: dollar-sign characters in non-regex replacement text were corrupting files. — [CHANGELOG.md#L129](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L129)

Corrupt conversation history moved from being erased to being **quarantined** in the same release — a small change that signals a maturing attitude to user data. — [CHANGELOG.md#L130](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L130)

v0.23.0 continued with rate-limit retry, abort actually cancelling in-flight tools, atomic plugin installation with integrity verification, and broadened auth self-healing. — [CHANGELOG.md#L102](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L102)

## Phase 6 — cost transparency and polish

v0.20.0 and v0.21.0 concentrate on making spend legible: model-fallback visibility in status bar, spinner, and exit summary; authoritative backend costs persisted to history; live cost tracking with a bounded range during multi-step turns. — [CHANGELOG.md#L150](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L150)

v0.25.0 brought configurable handling of messages typed during an active turn — the `defaultInputMode` setting — plus single-executable Windows standalone releases with isolated plugin support. — [CHANGELOG.md#L64](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L64)

v0.26.0 reads as an editing-experience release: bounded undo and redo, text recovery, drafts preserved through re-authentication, bounded large-file handling, binary-file protection, and symbolic-link exclusion. — [CHANGELOG.md#L34](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L34)

The most recent entries are narrow: v0.26.5 fixes Mac Finder file drops including URL-encoded filenames and spaces. — [CHANGELOG.md#L5](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L5)

## What the trajectory implies

The product is young and moving fast, and its investment has rotated through a legible sequence: terminal correctness → platform integration → runtime architecture → extensibility → security → cost transparency. Each phase's follow-on patches show the team absorbing the cost of the previous phase's bet. — [CHANGELOG.md#L276](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L276)

Two things are conspicuously absent from twenty-four releases and are fair questions to raise. There is no entry about local-model or offline support, consistent with the thin-client architecture being a firm commitment rather than a current-stage simplification. — [CHANGELOG.md#L100](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L100)

And LSP coverage remains TypeScript/JavaScript only, with "more languages will be added in future releases" — so polyglot enterprise codebases currently get text-heuristic code intelligence outside the TS/JS surface. — [docs/plugins.md#L471](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L471)

For a fast-moving product with undated guides, the practical operating rule follows directly: check the changelog before trusting any guide statement about behaviour, and prefer `/doctor` and direct observation over documentation when diagnosing a client issue. See `mono-foundry-doc-drift.md` for the four places this already matters. — [CHANGELOG.md#L107](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L107)

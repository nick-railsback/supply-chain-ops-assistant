# monō foundry — subagents

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary file: `docs/subagents.md` (content-hash `db488b37`); supporting `docs/daemon.md` (`ba6dce0b`), `CHANGELOG.md` (`d15d6afd`)

## Contents

- [Server-orchestrated, client-executed](#server-orchestrated-client-executed)
- [Lifecycle](#lifecycle)
- [Visual attribution](#visual-attribution)
- [Tool execution and the approval gap](#tool-execution-and-the-approval-gap)
- [Persistence limits](#persistence-limits)
- [Prompting for parallelism](#prompting-for-parallelism)
- [Constraints](#constraints)

## Server-orchestrated, client-executed

Subagents are independent child conversations the **backend** spawns mid-turn to work in parallel with the main agent. The orchestrator decides when to spawn and emits a `subagent_spawn` event on the parent's generate stream; the CLI receives it and launches a second loop for the child. — [docs/subagents.md#L22](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L22)

This is the thin-client model applied to concurrency, and it is the sharpest contrast with client-orchestrated harnesses: **you cannot request a subagent.** The CLI does not decide when to spawn children and has no API to ask for one. — [docs/subagents.md#L141](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L141)

Four properties define the model: spawning is concurrent and fire-and-forget so the parent stream keeps processing; each child has its own hidden Core conversation server-side; children execute IDE tool commands locally through the same registry as the parent; and **there are no grandchildren**. — [docs/subagents.md#L26](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L26)

Subagent spawning landed in v0.12.0 with independent tool routing and visual attribution; v0.13.1 made server-orchestrated subagent activity visible in the CLI via banners. — [CHANGELOG.md#L334](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L334)

## Lifecycle

The documented phases are spawn (backend emits `subagent_spawn`), running (the child consumes its own SSE stream and executes tools locally while the parent continues), completion (the child prints a finish banner and resolves on `done`/`complete`), turn end (**the parent awaits all in-flight children** before the turn completes), and cancellation. — [docs/subagents.md#L52](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L52)

Cancellation propagates through a shared `AbortSignal`: Ctrl-C/SIGINT cancels the parent and every in-flight child together, and an aborted child exits cleanly without an error message. — [docs/subagents.md#L58](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L58)

A crashing child is contained — a safety net prevents child failure from propagating to the parent. — [docs/subagents.md#L60](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L60)

At the daemon layer, child sessions are owned by the parent daemon sid and delivered through the owning frontend session, inheriting the parent's workspace context. — [docs/daemon.md#L103](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L103)

## Visual attribution

Child output lines carry a gutter prefix — two spaces, a dimmed pipe, a space — and start/finish banners are written unindented to the parent sink so they stand out. — [docs/subagents.md#L36](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L36)

Each child gets a four-character tag such as `[a3f2]` that distinguishes concurrent children in the banners. — [docs/subagents.md#L46](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L46)

There is deliberately **no child spinner** — the parent owns the spinner line, so child status comes only through text output and tool-run summaries. — [docs/subagents.md#L140](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L140)

## Tool execution and the approval gap

> **Read `mono-foundry-doc-drift.md` before relying on this section.** `docs/subagents.md` states that subagent mutations bypass approval mode, but `CHANGELOG.md` v0.22.0 states that sub-agent tool calls route through the parent session's approval gate. The guide predates the changelog entry and appears stale. Verify against the running build before advising anyone.

As written, the guide says mutating tools — `write_file`, `apply_diff`, `search_and_replace`, `delete_file`, `move_file`, `call_mcp_tool`, `code_runner` — are **auto-accepted** in subagents, with the diff preview still rendered but no approval prompt, because children run in the background and cannot block on user input. — [docs/subagents.md#L70](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L70)

It then states plainly that `--approve` or `/approve` applies to the **parent** turn only and that subagent mutations are not gated. — [docs/subagents.md#L72](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L72)

The contradicting release note is unambiguous: "Terminal and task-execution tools are now gated behind approval mode; sub-agent tool calls route through the parent session's approval gate." — [CHANGELOG.md#L123](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L123)

Supporting evidence that subagent approval plumbing exists: v0.16.2 fixed rejected-or-skipped tool rendering in **daemon subagent sessions**, which only makes sense if children surface approval outcomes. — [CHANGELOG.md#L215](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L215)

Command responses are POSTed back via `sendCommandResponse` on the child's own `commandId`, and the docs flag the load-bearing assumption: command IDs must be globally unique across parent and child streams, otherwise `childSid`/`conversationId` correlation would be needed. — [docs/subagents.md#L76](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L76)

## Persistence limits

Subagent transcripts are **not** written to the local conversation store — the child's conversation lives server-side and the CLI persists no child messages, tool calls, or plans. — [docs/subagents.md#L82](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L82)

What survives `/resume` is a lightweight `subagent_spawn` marker pushed into the parent's `assistantToolCalls`, recording the child's request and `childSid`. On resume you see that a subagent was spawned and what it was asked to do — but not what it did. — [docs/subagents.md#L84](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L84)

This is a real auditability gap for regulated work: local history cannot reconstruct child behaviour, so the server-side record is the only complete one. — [docs/subagents.md#L137](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L137)

Token accounting does account for children — the end-of-turn receipt prints three aligned lines labelled `cumulative`, `parent`, and `subagents` when children ran. — [docs/commands.md#L973](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L973)

Double-counting of subagent usage in daemon mode was a real bug, fixed in v0.22.0 — worth knowing if you are reconciling costs on an older build. — [CHANGELOG.md#L132](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L132)

## Prompting for parallelism

Because spawning is server-side, the only lever is how you frame the request. The documented advice is to structure requests that decompose into clearly separable components — two independent tasks such as "research the auth flow" plus "audit `src/api.ts` for unhandled error paths" are good candidates; a single tightly-coupled task is not. — [docs/subagents.md#L94](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L94)

Be explicit about scope, because children receive their own workspace context but **do not inherit the parent's in-progress reasoning** — a subtask must be self-contained to work. — [docs/subagents.md#L106](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L106)

Keep subtasks focused: children are lightweight loops without the parent's full persistence and approval machinery, so they suit research, analysis, drafting, and code review rather than long multi-step implementations needing interactive steering. — [docs/subagents.md#L128](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L128)

Mid-turn steering can target a specific child: `/clarify subagent <tag>` addresses a running child, while a bare `/clarify` always steers the parent. — [docs/commands.md#L434](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L434)

## Constraints

| Constraint | Detail |
|---|---|
| No grandchildren | `subagent_spawn` on a child stream is ignored |
| No local persistence | Only a spawn marker in the parent's tool-call history |
| No interactive approval | Per the guide; contradicted by v0.22.0 — see drift reference |
| No independent cancellation | Ctrl-C cancels parent and all children together |
| No child spinner | Parent owns the spinner line |
| Server-side orchestration | The CLI cannot request a subagent |

— [docs/subagents.md#L134](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L134)

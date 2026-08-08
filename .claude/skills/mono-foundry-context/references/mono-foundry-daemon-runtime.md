# monō foundry — daemon local runtime

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary file: `docs/daemon.md` (content-hash `ba6dce0b`); supporting `docs/commands.md` (`4de63eec`), `docs/security.md` (`c12add0b`)

## Contents

- [What the daemon is](#what-the-daemon-is)
- [Lifecycle and idle shutdown](#lifecycle-and-idle-shutdown)
- [Session isolation: sid and cwd](#session-isolation-sid-and-cwd)
- [Direct mode vs explicit daemon mode](#direct-mode-vs-explicit-daemon-mode)
- [Stale daemons after an update](#stale-daemons-after-an-update)
- [Troubleshooting](#troubleshooting)
- [Files](#files)

## What the daemon is

Since v0.15.0 the daemon runtime is the **default** for interactive sessions, with auto-start, idle shutdown, and graceful fallback to direct mode. — [CHANGELOG.md#L278](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L278)

The CLI remains the frontend; the daemon hosts the local control loop, the Core stream, local tool execution, subagent lifecycle, and bridge/session state. — [docs/daemon.md#L3](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L3)

It is local-only by construction: it binds to loopback, authenticates clients with a bearer token, and stores discovery and logs under `~/.monofoundry/`. It is not a remote network service. — [docs/daemon.md#L5](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L5)

## Lifecycle and idle shutdown

On startup the CLI checks daemon discovery metadata and health. If a ready daemon exists it attaches by creating an explicit cwd-aware session; otherwise it starts one in the background when daemon support is bundled for the install. — [docs/daemon.md#L33](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L33)

There is an asymmetry worth remembering: **CLI-auto-started daemons get a five-minute idle shutdown window; explicitly started daemons do not.** `monofoundry daemon start` keeps running until stopped unless you pass `--idle-ms` or set `SPIRE_IDLE_SHUTDOWN_MS`. — [docs/daemon.md#L35](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L35)

Note the environment variable there is `SPIRE_IDLE_SHUTDOWN_MS`, not a `MONOFOUNDRY_`-prefixed name — a leftover from an earlier product name that also shows up in `SPIRE_WORKSPACE_FOLDERS` for VS Code compatibility. The CLI-flag equivalent for auto-started daemons is `MONOFOUNDRY_DAEMON_IDLE_MS`, where `0` disables idle shutdown. — [docs/daemon.md#L125](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L125)

Lifecycle commands are `daemon status`, `daemon start`, `daemon stop`, `daemon restart`, `daemon logs [--lines n]`, and `doctor`. — [docs/daemon.md#L52](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L52)

The same diagnostics are reachable from inside the REPL as `/daemon status`, `/daemon logs [n]`, and `/doctor`, and they are explicitly safe to run **during** a turn — useful when a session is stuck and you do not want to lose it. — [docs/daemon.md#L65](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L65)

## Session isolation: sid and cwd

One daemon process can host multiple CLI or IDE frontends simultaneously. Each REPL or one-shot run creates a distinct logical daemon session id (`sid`) attached with an **immutable canonical cwd** plus workspace-folder metadata. — [docs/daemon.md#L87](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L87)

The isolation rules are specific and worth reading as a set, because they define what a multi-project workflow can and cannot do: cwd belongs to the session rather than the process; output for sid A reaches only sid A's frontend; daemon-local tools execute with sid A's cwd; responses are matched by sid plus request/command id; reconnects resume only that sid's replay buffer; and **reattaching the same sid with a different cwd is rejected**. — [docs/daemon.md#L91](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L91)

A `/resume` conversation id is *not* a daemon sid. Resuming a conversation in a new CLI creates a new sid; reconnecting an existing CLI process reuses its current sid and `Last-Event-ID` replay position. Conflating the two is the most likely source of confusion when debugging a session. — [docs/daemon.md#L101](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L101)

Subagent child sessions are owned by their parent daemon sid, tagged with the child sid for attribution but delivered through the owning frontend session, and they inherit the parent's workspace context — cross-workspace subagents are named as a possible future feature, not current behaviour. — [docs/daemon.md#L103](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L103)

## Direct mode vs explicit daemon mode

These are two different escape hatches and they fail in opposite directions. Default daemon mode is **intentionally recoverable**: if daemon startup or readiness fails before a turn begins, the CLI silently falls back to direct mode and runs the turn anyway. — [docs/daemon.md#L37](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L37)

Explicit daemon mode (`--daemon-client`) **fails closed** on startup, readiness, protocol, auth, or version-mismatch errors. Use it precisely when you want daemon problems surfaced rather than silently recovered — which is the mode you want while diagnosing a client's flaky install. — [docs/daemon.md#L127](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L127)

Explicit mode accepts `--daemon-port`, `--daemon-url`, and `--daemon-token`, with `MONOFOUNDRY_DAEMON_CLIENT`, `MONOFOUNDRY_DAEMON_URL`, `MONOFOUNDRY_DAEMON_PORT`, and `MONOFOUNDRY_DAEMON_TOKEN` as environment equivalents. — [docs/daemon.md#L119](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L119)

Direct mode is the third position: `--direct`, `--no-daemon`, or `MONOFOUNDRY_NO_DAEMON=1` runs against Core without attaching to or starting a daemon, and is described as the escape hatch for urgent work when the daemon is unhealthy. — [docs/daemon.md#L83](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L83)

## Stale daemons after an update

A running daemon keeps executing the code it was started with, so after an update the daemon can be older than the CLI that just launched. This is the single most likely post-update support ticket. — [docs/daemon.md#L142](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L142)

Resolution differs by mode: in default daemon mode an **idle** stale daemon is restarted automatically; a stale daemon with active sessions that stays protocol-compatible produces a warning and continues; and in explicit `--daemon-client` mode a version mismatch fails closed with a restart message. — [docs/daemon.md#L146](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L146)

## Troubleshooting

The docs ship a symptom→checks→recovery matrix covering daemon unreachable, auth expiry, bridge unavailable, version mismatch, stale discovery/socket/port data, wrong-cwd sid rejection, and tool routing timeouts. Two commands appear in nearly every row — `monofoundry doctor` and `monofoundry daemon status` — which makes them the right first move for any daemon-shaped complaint. — [docs/daemon.md#L153](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L153)

The recovery for a wrong-cwd or sid attach rejection is specifically **start a fresh CLI session for the new directory** — do not reuse an old sid across directories. This follows directly from the immutable-cwd rule above. — [docs/daemon.md#L160](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L160)

Stale discovery data should only be removed when diagnostics direct you to; the docs otherwise advise against hand-editing `daemon.json`. — [docs/daemon.md#L138](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L138)

Daemon hardening across releases is a visible theme: v0.23.0 added detached-session idle GC, SIGTERM/SIGHUP cleanup handlers, stale-config detection, forceful kill escalation, session-scoped managed terminals, and WebSocket protocol fixes. — [CHANGELOG.md#L112](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L112)

## Files

| Path | Purpose |
|---|---|
| `~/.monofoundry/daemon.json` | Discovery: URL, token, pid, version, protocol, boot id, log path |
| `~/.monofoundry/logs/daemon.log` | NDJSON daemon logs |
| `~/.monofoundry/config.json` | Auth credentials and user settings |
| `~/.monofoundry/projects/<slug>/conversations/` | Local conversation history |

— [docs/daemon.md#L131](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L131)

The security posture of the daemon is narrow and easy to state to a client: loopback-only, bearer-token authenticated, no remote surface — but local tools still run with the invoking user's full permissions, so the daemon is not an isolation boundary. — [docs/daemon.md#L165](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/daemon.md#L165)

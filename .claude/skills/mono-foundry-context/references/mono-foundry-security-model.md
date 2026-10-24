# monō foundry — security and trust model

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary file: `docs/security.md` (content-hash `c12add0b`); supporting `CHANGELOG.md` (`d15d6afd`), `docs/daemon.md` (`ba6dce0b`)

## Contents

- [The claim and its shape](#the-claim-and-its-shape)
- [Network surface](#network-surface)
- [Credential encryption at rest](#credential-encryption-at-rest)
- [Tool registry and local execution](#tool-registry-and-local-execution)
- [Approval mode — and what it does not cover](#approval-mode--and-what-it-does-not-cover)
- [Access control](#access-control)
- [Data minimisation and telemetry](#data-minimisation-and-telemetry)
- [Hardening recommendations](#hardening-recommendations)

## The claim and its shape

The security story follows from the thin client: the CLI does not choose which tools to run, does not perform web searches or call third-party APIs, keeps a small and predictable network footprint, and encrypts on-disk credentials with a key that is neither in the source nor in the config file. — [docs/security.md#L44](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L44)

These are unusually checkable claims for a vendor security page — each maps to something a client's security team can verify with a packet capture, a file listing, or a binary inspection. That verifiability is the argument, not the adjectives. — [docs/security.md#L61](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L61)

## Network surface

Seven endpoints are enumerated, and the doc asserts no others are contacted by the CLI itself. — [docs/security.md#L65](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L65)

| Endpoint | When | Purpose |
|---|---|---|
| `core.monoai.co` (configurable) | Every turn | Streaming, tool dispatch, uploads, auth, queries |
| `api.github.com` | `/update` or 24h startup check | Release check |
| `raw.githubusercontent.com` | Only on update install | Download install script |
| `app.monoai.co` (configurable) | Deep-links, opened in browser | Studio links |
| OAuth provider (Google/Microsoft) | Only during `auth login`, in browser | SSO |
| `127.0.0.1` | Default daemon-client mode | Local daemon transport |
| `127.0.0.1` | Only during `auth login` | Ephemeral OAuth callback |

The strong form of the claim: there is **no general-purpose HTTP client, no plugin download mechanism, and no way for the agent to instruct the CLI to call an arbitrary URL**. — [docs/security.md#L61](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L61)

Read that alongside the plugin system, which *does* download tarballs over HTTPS from GitHub and arbitrary URLs — the reconciliation is that plugin installation is a separate top-level CLI command driven by the user, not something the agent can trigger mid-turn. — [docs/plugins.md#L319](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L319)

Locally executed tools make no network calls; `code_runner` in particular writes to a local temp directory and runs the local interpreter rather than reaching a remote sandbox. Local MCP servers are the single named exception. — [docs/security.md#L79](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L79)

The `--endpoint`/`--app-url` derivation rule is worth knowing for staging environments: the app URL is derived by swapping the `app`↔`core` subdomain prefix, and derivation only succeeds for hostnames ending in `monoai.co` or `sprnt.ai`. Both values persist per-project. — [docs/security.md#L57](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L57)

## Credential encryption at rest

The threat model is stated narrowly and honestly: it protects against the config directory being **accidentally synced or leaked** (iCloud, Dropbox, a backup) and read on another machine. An attacker who already has the originating machine is explicitly out of scope, and source-code knowledge alone must not suffice to decrypt. — [docs/security.md#L89](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L89)

The token is encrypted with AES-256-GCM under a scrypt-derived key with a per-file random salt, keyed from either `MONOFOUNDRY_PASSPHRASE` or an OS machine identifier (macOS `IOPlatformUUID`, Linux `/etc/machine-id`, Windows `MachineGuid`). — [docs/security.md#L93](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L93)

On-disk form is a self-describing envelope `{v, alg, kdf, src, salt, iv, tag, data}`, and legacy plaintext tokens are upgraded automatically on the next save. **Only the `token` field is encrypted** — endpoint, user info, org ID, and login method stay readable for debuggability. — [docs/security.md#L100](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L100)

Directory permissions are hardened to `0700` and the config file to `0600`, best-effort and a no-op on Windows; writes are atomic via temp-file-then-rename so no reader observes a half-written config. — [docs/security.md#L106](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L106)

Setting `MONOFOUNDRY_PASSPHRASE` is the documented upgrade that makes credentials non-decryptable **even on the originating machine** — the one hardening step that changes the threat model rather than narrowing exposure. — [docs/security.md#L285](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L285)

## Tool registry and local execution

The executable tool set is **fixed at build time**, compiled into the binary, spanning file operations, search, terminal, tasks, code execution, git, workspace, skills, diagnostics, and MCP. Unknown tool names return an error without executing. — [docs/security.md#L124](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L124)

All tools run locally with the invoking user's permissions — no privilege escalation, no alternate user, no remote sandbox. The CLI's filesystem and process access is exactly the running user's, no more and no less. — [docs/security.md#L143](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L143)

Every tool execution is wrapped in a **60-second watchdog** so a hung tool returns an error rather than wedging the turn; the doc notes the underlying process may still be alive afterwards, with per-tool timeouts handling cleanup. — [docs/security.md#L149](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L149)

Containment hardened over time: v0.22.0 added symlink-aware containment to the workspace root for file, search, and terminal tools, and stripped sensitive environment variables from child processes spawned during a turn. — [CHANGELOG.md#L125](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L125)

## Approval mode — and what it does not cover

> **This section contains the corpus's most consequential documentation drift.** See `mono-foundry-doc-drift.md` before quoting any of it to a client.

Seven tools are documented as intercepted when approval mode is on: `write_file`, `apply_diff`, `search_and_replace`, `delete_file`, `move_file`, `call_mcp_tool`, and `code_runner`. — [docs/security.md#L155](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L155)

The diff preview is **always rendered, even when approval mode is off** — so you always see what is about to change; the prompt is what approval mode adds. Rejecting with guidance sends your message back as a command error so the agent adapts; skipping silently continues. — [docs/security.md#L167](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L167)

Approval mode is **REPL-only**: in one-shot mode the diff preview renders but no prompt appears — which means `monofoundry "do the thing"` is unattended-execute by construction. — [docs/security.md#L172](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L172)

The design note then claims terminal tools (`run_terminal`, `spawn_terminal`, `write_terminal`, `kill_terminal`) and `run_task` are deliberately **not** gated, reasoning that gating every build/test/lint/git command would make approval mode impractical, while `code_runner` *is* gated because its shell-fallback mode can execute arbitrary commands. — [docs/security.md#L174](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L174)

That claim is contradicted by the v0.22.0 release note: "Terminal and task-execution tools are now gated behind approval mode." — [CHANGELOG.md#L123](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L123)

Two further v0.22.0/v0.23.0 changes also postdate the guide: dismissing an approval prompt with Esc or Ctrl-C now **skips** the tool rather than accepting it, and an unconditional five-minute approval timeout that contradicted documented behaviour was removed. — [CHANGELOG.md#L124](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L124)

## Access control

RBAC is enforced **server-side** on every API call; the CLI implements no access control of its own and simply presents credentials. It cannot bypass these controls because it has no path to resources the backend does not authorise. — [docs/security.md#L182](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L182)

An `X-Organisation-Context` header scopes every call to the active organisation, covering models, conversations, projects, and work items; users may belong to several orgs and switch between them. — [docs/security.md#L192](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L192)

Sessions can be further scoped to a project and work item via `--project`, `/project`, and `/workitem`, linking the agent's context to that item on the backend — an additional narrowing beyond the user's full accessible surface. — [docs/security.md#L196](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L196)

Platform connections to external services are managed server-side under the same RBAC, with the backend mediating all access — the CLI never contacts them directly. — [docs/security.md#L210](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L210)

Agent-initiated external lookups are screened by a **SafeLinks** service that checks target hosts against threat intelligence before any request, which the doc frames explicitly as prompt-injection defence performed centrally rather than in the client. — [docs/security.md#L220](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L220)

Authentication is either an API key (`sk-`/`sk_`, sent as `X-API-Key`) or OAuth bearer token; the OAuth flow opens the browser, starts an ephemeral `127.0.0.1` server on a random port to capture the callback, accepts a manually pasted redirect URL for headless use, and closes after receipt or a five-minute timeout. — [docs/security.md#L237](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L237)

Note the practical caveat from the README: API-key login **disables seeing conversations in your personal conversation list**, which is a real trade-off for CI or shared-service accounts. — [README.md#L44](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L44)

## Data minimisation and telemetry

The CLI collects, transmits, and stores **no** analytics, usage telemetry, or tracking data, and does not phone home or beacon. — [docs/security.md#L250](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L250)

What is sent is enumerated against what is not: messages and history, workspace context, tool results, and explicit binary uploads — but not arbitrary file contents, full directory listings, environment variables, shell history, or system logs. — [docs/security.md#L265](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L265)

Text files are **never** uploaded; contents cross the wire only as a tool result when the agent reads them. Binary uploads are explicit and capped at 20 MB. — [docs/security.md#L272](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L272)

## Hardening recommendations

Six measures are recommended: approval mode, sandboxed execution (container, VM, or restricted account), a dedicated workspace via `--cwd` rather than pointing at home, `MONOFOUNDRY_PASSPHRASE`, network egress allowlisting of `core.monoai.co` plus GitHub update endpoints and loopback, and MCP server config review. — [docs/security.md#L280](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L280)

The README states the default posture without softening it: the tool assumes all permissions of the running user, so use `/approve` for step approval and sandbox it for additional protection. For a client deployment, treat OS-level sandboxing as the real isolation boundary — approval mode is a review gate, not containment. — [README.md#L5](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L5)

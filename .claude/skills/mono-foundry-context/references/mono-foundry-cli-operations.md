# monō foundry — CLI, REPL, and operations

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary file: `docs/commands.md` (content-hash `4de63eec`); supporting `README.md` (`82d6f7b4`), `docs/files.md` (`95698f20`)

## Contents

- [Invocation and flags](#invocation-and-flags)
- [Command families](#command-families)
- [Steering a running turn](#steering-a-running-turn)
- [Project and work-item binding](#project-and-work-item-binding)
- [Files and attachments](#files-and-attachments)
- [Shell mode](#shell-mode)
- [Cost and token reporting](#cost-and-token-reporting)
- [Keybindings worth knowing](#keybindings-worth-knowing)

## Invocation and flags

`monofoundry` with no argument opens the interactive REPL; with a message it runs one-shot. Remember that one-shot mode renders diff previews but never prompts, so it is unattended by construction. — [README.md#L53](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L53)

The flag surface covers `--version`, `--cwd`, `--endpoint`, `--app-url`, `--model`, `--project`, `--resume`, `--approve`, the four daemon flags, and `--direct`/`--no-daemon`. — [docs/commands.md#L54](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L54)

Auth is a top-level subcommand family: `auth login` (Google default, `--microsoft`, `--apikey`), `auth status`, and `auth logout`, with credentials persisted to `~/.monofoundry/config.json`. — [README.md#L41](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L41)

One onboarding wrinkle to expect on a client machine: browser-based login currently requires copying the `vscode://` redirect URL out of the browser by right-clicking the "Open monō ai" link and choosing Copy Link Address. — [README.md#L49](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L49)

## Command families

Slash commands group into Core, Conversation, Session, Files, Auth, Organisation, Project, Skills, and Daemon Diagnostics. Typing `/` triggers tab-completion, and **unrecognised slash commands are treated as normal chat messages** rather than erroring. — [docs/commands.md#L113](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L113)

Core covers `/help`, `/quit` (`/exit`), `/new` (`/clear`), `/reset`, `/stash`, `/update`, `/init`, `/daemon`, and `/doctor`. — [docs/commands.md#L117](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L117)

`/reset` and `/new` are deliberately different: `/reset` clears model, utility, nosave, and approval, but **not** the conversation ID, project/work-item selection, input history, or token usage. — [docs/commands.md#L156](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L156)

Conversation commands are `/resume`, `/conversations` (with a `studio` sub-command searching org-wide), `/tokens` (`/costs`), `/star`, `/rename`, `/link`, and `/unlink`. — [docs/commands.md#L238](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L238)

Studio URLs are accepted anywhere an ID is — `/resume`, `/conversations studio`, `/link`, and `/workitem` all extract the ID or key from the last path segment. — [docs/commands.md#L282](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L282)

Reset synonyms were standardised in v0.23.0: `clear`, `default`, `none`, and `reset` all work across `/model`, `/theme`, `/project`, and `/workitem`. — [CHANGELOG.md#L108](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L108)

**Undocumented command:** `/utility` and `--utility` exist and select the agent "utility" type (values such as `monocode` and `research`), but no Session-table row documents them. Their existence is attested only by the `Alt/Opt-U` prose, the `/reset` description, and two changelog entries. — [docs/commands.md#L881](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L881)

## Steering a running turn

`/clarify <msg>` injects a clarification at the next tool boundary while the agent works; when idle it is sent as an ordinary turn. — [docs/commands.md#L430](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L430)

Setting `"defaultInputMode": "clarify"` in `~/.monofoundry/config.json` makes plain typed text steer the running turn, so the `/clarify` prefix becomes optional; `"interrupt"` (the default) queues text as a separate follow-up instead. — [docs/commands.md#L432](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L432)

Explicit commands keep their behaviour regardless of mode: `/clarify` always steers the parent, `/clarify subagent <tag>` targets a running child, safe mid-turn commands execute immediately, and other slash commands or `!` shell input wait as follow-ups. — [docs/commands.md#L434](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L434)

`/nosave` runs turns without persisting them to the backend while still keeping local history as context, and can wrap either a message or another slash command. — [docs/commands.md#L449](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L449)

## Project and work-item binding

`/project` selects a workspace project by ID, key, or name, persisting to `~/.monofoundry/projects/<slug>/meta.json`. — [docs/commands.md#L641](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L641)

`/workitem` requires a project first and supports `create <title>`, `implement <tag|id|url>`, direct selection, and `clear`. — [docs/commands.md#L669](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L669)

`/workitem implement` is the interesting one for demos: it retrieves the work item, links the conversation to it, and starts implementing in a single step — the tightest expression of the platform-integrated workflow, and what the repo's demo GIF shows. — [docs/commands.md#L672](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L672)

Switching organisation cascades: `/org` clears and refreshes the model cache, resets project/work-item selection, and starts a new conversation, because each is homed within an org. — [docs/commands.md#L615](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L615)

## Files and attachments

Three attachment paths exist: inline `@`-paths, `/attach <path>`, and `/paste` for clipboard images. Binary files upload; text files are left for the agent to read with its file tools. — [docs/files.md#L24](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/files.md#L24)

An `@` must start the message or follow whitespace, so email addresses are not matched; duplicates are de-duplicated and the message text is never modified — only file IDs are attached. — [docs/files.md#L47](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/files.md#L47)

Classification is two-stage: a known-binary extension fast path, then content sniffing of the first 8 KB where a NUL byte is definitive and a >30% non-text byte ratio classifies as binary. Empty files count as text and are skipped. — [docs/files.md#L119](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/files.md#L119)

Upload limit is 20 MB, empty files are rejected, and unknown extensions fall back to `application/octet-stream`. — [docs/files.md#L131](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/files.md#L131)

`/paste` needs a platform helper — `pngpaste` on macOS (with an AppleScript fallback), `xclip` or `wl-paste` on Linux — and is **not supported on Windows**. — [docs/files.md#L144](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/files.md#L144)

## Shell mode

Any input starting with `!` runs the remainder through `bash -c` locally with a 60-second timeout, printing output above the prompt without involving the agent. — [docs/commands.md#L761](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L761)

This is a genuinely useful escape hatch during a session — run the tests yourself, check `git status` — without spending a turn or context on it. — [docs/commands.md#L766](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L766)

## Cost and token reporting

`/tokens` (alias `/costs`) breaks usage down across Session, Conversation, Project, and Overall tiers, with per-model rows shown only when a tier spans more than one model, sorted by total tokens descending. — [docs/commands.md#L300](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L300)

The end-of-turn receipt reports input tokens with a cache breakdown — `✧` uncached, `↻` cache-read, `✎` cache-write — plus output, total, cost, and elapsed time. **Interrupted turns print no receipt**, because they carry no authoritative usage. — [docs/commands.md#L964](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L964)

Model fallbacks are surfaced explicitly: indented lines below the receipt list each fallback model and its approximate token total. — [docs/commands.md#L975](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L975)

Costs prefer the persisted backend `task_cost` total and fall back to rate-based calculation only when no persisted cost exists — so quoted figures are authoritative rather than estimated wherever possible. — [docs/commands.md#L989](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L989)

Since v0.26.3, live in-progress estimates are shown as **bounded ranges** rather than point values, narrowed by known input and priced separately for cached and non-cached usage. — [CHANGELOG.md#L17](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L17)

The status bar carries model, utility, and org on the left; tokens/cost, approval, no-save, Studio link, and project on the right. `Alt/Opt-T` toggles cost↔tokens and `Alt/Opt-L` cycles the Studio link through conversation → work item → project. — [docs/commands.md#L903](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L903)

## Keybindings worth knowing

The line editor implements a readline-compatible set — `Ctrl-A`/`Ctrl-E`, `Ctrl-K`/`Ctrl-U`/`Ctrl-W` with a one-slot kill buffer, `Ctrl-Y` yank, `Ctrl-Z` undo, and word-wise `Ctrl-←`/`Ctrl-→`. — [docs/commands.md#L786](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L786)

`Ctrl-X Ctrl-E` opens the buffer in `$VISUAL`/`$EDITOR` (falling back to `vi`) as a true two-key chord, mirroring bash/zsh readline; a single trailing newline is stripped on return. — [docs/commands.md#L832](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L832)

`Ctrl-S` is a LIFO stash: first press with a non-empty buffer stashes and clears; a press with an empty buffer pops the most recent entry back. `/stash` with no argument opens a picker over all entries. — [docs/commands.md#L821](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L821)

`Alt/Opt-M` and `Alt/Opt-U` open the model and utility pickers **without clearing the input buffer**, applying to the next turn and never interrupting the current one. — [docs/commands.md#L853](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L853)

`Ctrl-C` is context-dependent: it aborts a generating turn, clears a non-empty buffer, or arms a ~2-second double-press exit window when idle and empty. — [docs/commands.md#L804](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L804)

Multi-line input uses `Shift-Enter`/`Alt-Enter` for a literal newline while `Enter` always submits; bracketed paste preserves original newlines. — [docs/commands.md#L1035](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L1035)

Input history is persisted **per project** at `~/.monofoundry/projects/<slug>/history`, and pressing `↑` on an empty buffer recalls the most recently queued message for editing, removing it from the queue. — [docs/commands.md#L1027](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L1027)

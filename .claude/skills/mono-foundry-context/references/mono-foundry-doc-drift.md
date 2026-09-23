# monō foundry — documentation drift and defects

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Derived by cross-reading `docs/security.md` (`c12add0b`), `docs/subagents.md` (`db488b37`), `docs/plugins.md` (`f1cb1ea7`), and `docs/commands.md` (`4de63eec`) against the dated `CHANGELOG.md` (`d15d6afd`)

This reference exists because the corpus is a **docs-only distribution repo** — there is no source code to check the guides against. Within the hub repository the only internal cross-check available is the dated, versioned changelog, and running that check surfaces the four findings below. Treat this as the trust map for everything else in this contextualizer.

A **second cross-check axis** now exists and is covered separately. The three first-party plugins are registered sources with their own undated READMEs and dated changelogs, so the same check runs three more times — and additionally *across* repositories, because the hub's first-party section is a drifted copy of those READMEs. Those findings, including a licence contradiction and an install command naming a non-existent repository, live in `mono-foundry-first-party-plugins.md`. — [docs/plugins.md#L445](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L445)

## Contents

- [Why this check is possible at all](#why-this-check-is-possible-at-all)
- [Finding 1 — terminal tools and approval mode](#finding-1--terminal-tools-and-approval-mode)
- [Finding 2 — subagent approval](#finding-2--subagent-approval)
- [Finding 3 — merge-conflict marker in plugins.md](#finding-3--merge-conflict-marker-in-pluginsmd)
- [Finding 4 — undocumented /utility command](#finding-4--undocumented-utility-command)
- [How to use these](#how-to-use-these)

## Why this check is possible at all

The repository contains fourteen files and no application source: a README, a changelog, an installer, a demo GIF, a licence, and nine documentation pages. — [README.md#L119](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L119)

The changelog is dated and semver-tagged down to patch releases, with the head entry at v0.26.5 on 2026-08-05. That makes it a reliable timeline against which undated prose can be aged. — [CHANGELOG.md#L3](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L3)

The guides carry no version stamps or "last updated" dates, so a reader has no signal that a given page predates the build they are running. That absence is the root cause of all four findings below. — [docs/index.md#L1](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/index.md#L1)

## Finding 1 — terminal tools and approval mode

**Severity: high.** This one changes the security answer you would give a client.

`docs/security.md` states as a deliberate design note that terminal tools (`run_terminal`, `spawn_terminal`, `write_terminal`, `kill_terminal`) and `run_task` are **not** gated by approval mode, arguing that gating every build/test/lint/git command would make approval mode impractical. — [docs/security.md#L174](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L174)

The v0.22.0 release note of 2026-07-07 says the opposite: "Terminal and task-execution tools are now gated behind approval mode." — [CHANGELOG.md#L123](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L123)

The changelog is dated and the guide is not, and the head release is v0.26.5 — roughly four minor versions past the change. The likely reading is that `security.md` is stale and terminal tools **are** now gated, but this cannot be confirmed from the repository alone because no source ships here. — [CHANGELOG.md#L121](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L121)

Two adjacent v0.22.0/v0.23.0 changes are also unreflected in the guide: Esc or Ctrl-C on an approval prompt now **skips** rather than accepts, and an unconditional five-minute approval timeout "that contradicted the documented behaviour" was removed — a changelog entry that is itself an admission of prior doc drift. — [CHANGELOG.md#L107](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L107)

## Finding 2 — subagent approval

**Severity: high.** Same root cause, different page, and it inverts a safety property.

`docs/subagents.md` states that mutating tools are auto-accepted in subagents, and that `--approve`/`/approve` applies to the parent turn only with subagent mutations not gated. — [docs/subagents.md#L72](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L72)

The same v0.22.0 entry states that "sub-agent tool calls route through the parent session's approval gate." — [CHANGELOG.md#L123](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L123)

Corroborating evidence that subagent approval plumbing exists: v0.16.2 fixed rejected-and-skipped tool indicators specifically in daemon subagent sessions, which presupposes children can be rejected or skipped. — [CHANGELOG.md#L215](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L215)

The consequence of getting this wrong runs in the dangerous direction. The guide tells a security-conscious user that enabling approval mode leaves a gap, which could push them to avoid subagent-friendly prompts entirely or to over-state the risk in a client review. — [docs/subagents.md#L118](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/subagents.md#L118)

## Finding 3 — merge-conflict marker in plugins.md

**Severity: low, but it is a visible quality signal.**

Line 37 of `docs/plugins.md` is the literal string `||||||| Stash base` — the middle marker of a three-way `git stash` conflict, committed unresolved. — [docs/plugins.md#L37](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L37)

No `<<<<<<<` or `>>>>>>>` accompanies it, which means the conflict was "resolved" by keeping both sides and deleting only the outer markers. The result is two consecutive sections — "Runtime isolation" and "Runtime contract" — that are competing revisions of the same passage. — [docs/plugins.md#L35](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L35)

The two sections happen to be complementary rather than contradictory — one covers the Windows/npm entrypoint split, the other the Bun-runtime constraint — so no information is lost, but the boundary is unreviewed text and the marker renders literally in the published Markdown. — [docs/plugins.md#L39](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L39)

A grep for conflict markers across every `.md` and `.sh` in the repo returns this one line and nothing else, so it is isolated rather than systemic. — [docs/plugins.md#L37](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L37)

## Finding 4 — undocumented /utility command

**Severity: low.** A first-class feature with no reference entry.

"Utility" is a real session dimension: it appears as a status-bar segment shown when explicitly selected, it persists per project directory, and `/reset` lists clearing "the selected utility type and on-disk utility cache" among its four resets. — [docs/commands.md#L907](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L907)

`Alt/Opt-U` is documented as opening the utility picker, and its prose explicitly references typing `/utility` as the alternative — "no need to type `/utility` and submit". — [docs/commands.md#L881](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L881)

Yet no row for `/utility` exists in the Session command table, which lists only `/model`, `/approve`, `/clarify`, `/nosave`, and `/theme`. — [docs/commands.md#L380](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L380)

The changelog confirms both forms shipped: v0.12.1 added "`--utility` and `/utility` options to change the utility used by the tool", and v0.14.0 fixed `/utility` listing utilities outside the current organisation. — [CHANGELOG.md#L326](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L326)

The observable values are `monocode` and `research`, visible only in the `Alt/Opt-U` picker example — there is no documented list of utilities or explanation of what a utility changes about agent behaviour. — [docs/commands.md#L890](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L890)

## How to use these

For interview or client conversations, the safe framing is to state the documented behaviour, name the changelog entry that supersedes it, and say which you would verify first against a live build. That reads as rigour rather than fault-finding, and it is the honest position given a docs-only repository. — [CHANGELOG.md#L121](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L121)

The verification path for findings 1 and 2 is short: enable `/approve`, ask for something that triggers a terminal command, and observe whether a prompt appears; then frame a request likely to spawn a subagent and observe whether child mutations prompt. Both are single-session checks. — [docs/security.md#L155](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/security.md#L155)

Findings 3 and 4 are the kind of low-cost, high-signal contributions that make a good first pull request against a docs repo, if that is a route you want to take. — [docs/plugins.md#L37](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L37)

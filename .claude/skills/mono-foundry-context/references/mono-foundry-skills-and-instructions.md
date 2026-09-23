# monō foundry — skills and agent instructions

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary file: `docs/skills.md` (content-hash `191c95f3`); supporting `docs/index.md` (`77dfbfb3`), `docs/commands.md` (`4de63eec`)

## Contents

- [The two context surfaces](#the-two-context-surfaces)
- [Skill discovery and precedence](#skill-discovery-and-precedence)
- [SKILL.md format](#skillmd-format)
- [How skills reach the agent](#how-skills-reach-the-agent)
- [Agent instruction files](#agent-instruction-files)
- [The ecosystem-compatibility bet](#the-ecosystem-compatibility-bet)
- [Building on this surface](#building-on-this-surface)

## The two context surfaces

There are two distinct ways to give the agent standing context, and they behave differently. **Skills** are invocable instruction sets the agent chooses to load; **agent instruction files** are ambient project context loaded every turn. Both are auto-detected from disk with no registration step. — [README.md#L5](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/README.md#L5)

A skill is a markdown file with optional YAML frontmatter: frontmatter declares metadata, the body holds the instructions the agent follows when the skill is invoked. — [docs/skills.md#L24](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L24)

Discovery is deliberately **stateless** — skills are re-scanned on demand, not watched. The docs tie this directly to the thin-client model: no background processes, no cached state to invalidate. — [docs/skills.md#L26](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L26)

## Skill discovery and precedence

Twelve directories are scanned in a fixed order, and **the first directory to produce a skill with a given name wins**. Workspace directories are scanned before home directories, so project-level skills override user-level ones. — [docs/skills.md#L34](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L34)

Workspace order is `.monofoundry/skills/`, `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.codex/skills/`, `.github/skills/`. — [docs/skills.md#L38](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L38)

Home order continues with `~/.monofoundry/skills/`, `~/.claude/skills/`, `~/.agents/skills/`, `~/.cursor/skills/`, `~/.codex/skills/`, `~/.gemini/config/skills/`. — [docs/skills.md#L49](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L49)

Each discovered skill carries a **source label** naming the ecosystem it came from, and that label is surfaced both in `/skills` output and in the workspace context sent to the agent. — [docs/skills.md#L60](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L60)

Symlinked skill directories are followed — the common dotfiles-repo layout works, and dangling symlinks are silently skipped rather than erroring. — [docs/skills.md#L178](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L178)

## SKILL.md format

Frontmatter fields are `name` (defaults to the directory name), `description` (defaults to `"Skill: <name>"`), `tools`, `context`, `trigger`, and `tags`; unknown keys are silently ignored. — [docs/skills.md#L91](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L91)

One field deserves a warning label: **`tools` is informational and does not restrict the agent's available tools.** If you are used to harnesses where a tools list is an allowlist, this is not that — declaring `tools: [read_file]` does not prevent the skill's turn from writing files. — [docs/skills.md#L95](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L95)

Similarly, `trigger` currently documents only `manual`, so there is no documented auto-trigger mechanism — skills are invoked explicitly by the agent's `invoke_skill` tool or by the user's slash command. — [docs/skills.md#L97](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L97)

File-naming resolution tries `<dir>/SKILL.md` first, then `<dir>/<name>.md` as a fallback; standalone `SKILL.md`, `AGENTS.md`, or `CLAUDE.md` files (case-insensitive) directly inside a skills directory are also recognised, taking the skill name from the parent directory. — [docs/skills.md#L104](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L104)

The frontmatter parser supports YAML block scalars — `|` literal and `>` folded — plus both inline arrays and block lists for array fields. — [docs/skills.md#L123](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L123)

## How skills reach the agent

Three surfaces, and they are worth distinguishing because they have different costs. The agent gets two tools: `list_skills` returns all discovered skills with metadata, and `invoke_skill` loads a skill body and returns it to the agent, with `"none"` or `"deactivate"` clearing the active skill. — [docs/skills.md#L150](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L150)

Every discovered skill's name, first description line, and source label are included in the workspace context sent at the start of each turn — so skill *descriptions* are a standing per-turn token cost, while skill *bodies* load on demand. That is the progressive-disclosure seam to design against. — [docs/skills.md#L157](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L157)

In the REPL, `/skills` lists everything discovered and `/<skill-name> [arg]` runs a skill as a full agent turn with the optional argument appended to the body. — [docs/skills.md#L161](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L161)

Skill names are slugified into command names: lowercased, non-alphanumerics replaced with hyphens, leading/trailing hyphens stripped — so `"Commit Msg"` becomes `/commit-msg`. — [docs/skills.md#L164](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L164)

Built-in commands take precedence over skill commands on collision, and a skill whose slug collides with a built-in such as `/help` is simply **not registered** — silently unavailable as a slash command, though still invocable by the agent. — [docs/skills.md#L172](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L172)

## Agent instruction files

Project instructions resolve through their own fallback chain: `~/.monofoundry/MONOFOUNDRY.md` primary, with `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.agents/AGENTS.md`, `~/.gemini/GEMINI.md`, and `~/.cursorrules` as secondaries. — [docs/index.md#L50](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/index.md#L50)

v0.11.0 is where that multi-format support landed, and its changelog entry names a broader set including `.github/copilot-instructions.md` with priority fallback. — [CHANGELOG.md#L344](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L344)

`/init` scaffolds a project `MONOFOUNDRY.md` from detected metadata: project name from `package.json`, package manager inferred from lock files, frameworks (Next.js, Vite, Vue, Svelte, Angular, Express, React), languages (TypeScript, JavaScript, Python, Rust, Go, Java), and scripts with human-friendly descriptions. — [docs/commands.md#L209](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L209)

The generated file deliberately leaves `## Architecture` and `## Conventions` as placeholders for human or agent fill-in, and the context cache is cleared on write so instructions load on the next turn. — [docs/commands.md#L232](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L232)

## The ecosystem-compatibility bet

Read the three fallback chains together — skills, MCP configs, and instruction files each read Claude Code, Cursor, Codex, Copilot, and Antigravity locations — and a deliberate go-to-market choice emerges: a developer with an existing agent setup gets working context on first run with zero migration. — [docs/index.md#L46](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/index.md#L46)

This is a genuine adoption lever and worth naming explicitly in a client conversation: the switching cost of trying monō foundry inside an existing repo is close to zero, because the repo's `.claude/skills/` and `CLAUDE.md` are already valid inputs. — [docs/skills.md#L58](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L58)

The corresponding risk is precedence surprise: a stale `~/.claude/skills/deploy/SKILL.md` silently shadows nothing (home loses to workspace) but a stale *workspace* `.claude/skills/` entry beats the `.monofoundry/` one you just wrote, because `.monofoundry/skills/` is first only within its own scope tier. — [docs/skills.md#L36](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L36)

## Building on this surface

For a project that needs to *guide* the agent, skills are the cheapest extension point — a directory and a markdown file, no build step, no manifest, no install. — [docs/skills.md#L186](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L186)

For a project that needs *new capability*, skills cannot help: they add instructions, not tools. Reach for MCP (`mono-foundry-mcp-servers.md`) for user-scoped tools, or a plugin (`mono-foundry-plugins.md`) when you need to register or override tools, add slash commands, or ship a highlighter or theme. — [docs/skills.md#L28](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/skills.md#L28)

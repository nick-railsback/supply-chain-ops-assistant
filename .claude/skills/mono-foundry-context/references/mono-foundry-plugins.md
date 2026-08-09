# monō foundry — plugin system

Source: `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190`
Primary file: `docs/plugins.md` (content-hash `f1cb1ea7`); supporting `CHANGELOG.md` (`d15d6afd`)

## Contents

- [What a plugin is](#what-a-plugin-is)
- [Runtime isolation and the Bun constraint](#runtime-isolation-and-the-bun-constraint)
- [Permissions](#permissions)
- [Installation sources and IDs](#installation-sources-and-ids)
- [Configuration and schema validation](#configuration-and-schema-validation)
- [Storage layout](#storage-layout)
- [Restart semantics](#restart-semantics)
- [First-party plugins](#first-party-plugins)
- [Known defect in this document](#known-defect-in-this-document)

## What a plugin is

A plugin is a self-contained package with a `monofoundry.plugin.json` manifest declaring name, version, entry point, permissions, and contributions. The CLI downloads, validates, and installs it into a local store, then loads enabled plugins at session start. — [docs/plugins.md#L32](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L32)

Five contribution types are available: **tools** (register new ones or override built-ins), **commands** (slash commands in the REPL), **LSP**, **syntax highlighting**, and **configuration** (a schema users can set per workspace). — [docs/plugins.md#L49](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L49)

This is the deepest extension point in the product and the only one that can **override a built-in tool** — which is exactly how the first-party LSP plugin replaces text-heuristic code intelligence with real language-server results. — [docs/plugins.md#L453](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L453)

Plugin management is entirely CLI-side — `monofoundry plugin <command>` — and is explicitly **not** available as REPL slash commands. — [docs/commands.md#L93](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/commands.md#L93)

## Runtime isolation and the Bun constraint

Plugins run in an isolated child process communicating over the existing IPC protocol. Windows standalone binaries re-invoke the installed executable in an internal plugin-host mode, so a Windows install contains only `monofoundry.exe`; npm/source and Node development builds use the emitted `dist/plugins/host/bootstrap.mjs` entrypoint. — [docs/plugins.md#L36](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L36)

The constraint that will actually bite a plugin author: **standalone binaries use an embedded Bun runtime and do not guarantee a stock Node.js runtime.** Plugins must not assume a separately installed `node`, Node-only built-ins, or an ESM `__dirname` global. — [docs/plugins.md#L43](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L43)

For portable asset lookup the documented pattern is `new URL("./asset", import.meta.url)` converted with `fileURLToPath()` when a filesystem path is needed; the manifest's `moduleType` must match the entry module format (`esm` or `cjs`). — [docs/plugins.md#L43](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L43)

Isolation arrived in v0.18.1, which moved plugins into a separate process with managed activation, health monitoring, and bounded restarts, and **removed legacy in-process execution** outright. — [CHANGELOG.md#L173](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L173)

## Permissions

Every plugin declares a **non-empty** `permissions` array, and the runtime gates each capability behind its permission — using an undeclared capability throws. — [docs/plugins.md#L388](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L388)

The permission vocabulary is finer-grained than most plugin systems, and notably splits workspace-internal from workspace-external reads and localhost from external network: `workspace:read`, `workspace:read:external`, `workspace:write`, `process:spawn`, `network:localhost`, `network:external`, `config:read`, `config:write`, `storage:read`, `storage:write`, plus the parameterised `tool:provide:<name>`, `tool:override:<name>`, and `command:provide:<name>`, and the flat `highlighter:provide` and `theme:provide`. — [docs/plugins.md#L390](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L390)

The parameterised forms are the interesting part for a security review: a plugin cannot broadly "provide tools", it must name each tool it provides or overrides in its manifest, and that list is displayed before enabling. — [docs/plugins.md#L408](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L408)

Hardening landed progressively: v0.18.1 added HTTPS-only downloads with size and timeout limits, archive entry validation, package integrity verification before loading, stricter manifest validation, workspace read containment, symlink escape prevention, and constrained process spawns. — [CHANGELOG.md#L179](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L179)

v0.22.0 then required explicit permission consent for enabling, installing, and running plugin lifecycle hooks; v0.23.0 made installation atomic with integrity verification and required **re-consent before re-enabling an updated plugin**. — [CHANGELOG.md#L105](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L105)

## Installation sources and IDs

Four source types are accepted: GitHub release (`github:owner/repo[@tag]`), bare GitHub URL, direct HTTPS tarball URL, and local path (requiring `--dev`). — [docs/plugins.md#L319](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L319)

`--dev` unlocks local-path installs and GitHub *branch* archives, and **skips hash verification and release validation** with a printed warning — fine for development, not for anything a client runs. — [docs/plugins.md#L328](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L328)

Set `GITHUB_TOKEN` when hitting API rate limits or installing from private repos; the installer uses it for both API calls and tarball downloads. — [docs/plugins.md#L341](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L341)

The installer looks for the manifest at the archive root, then `package/`, then a single subdirectory — the last covering GitHub's `{repo}-{ref}/` archive layout. — [docs/plugins.md#L345](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L345)

IDs are derived from the source and stable across reinstalls: `github:owner/repo`, `url:hostname/path`, or `local:dir_basename`. The ID is the canonical key in the lockfile, config, and tool registry. — [docs/plugins.md#L359](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L359)

Update checking compares the GitHub release asset URL against the lockfile's `resolved` field — one API call per plugin, no download for the check. URL and local-path plugins **cannot** be update-checked, because there is no version API to query. — [docs/plugins.md#L165](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L165)

## Configuration and schema validation

Config is set with dot notation, creating intermediate objects automatically, and values are parsed as JSON first with a raw-string fallback — so `true` becomes a boolean and `hello` stays a string. — [docs/plugins.md#L223](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L223)

When a manifest declares `contributes.configuration.schema`, the **full resulting config object** is validated before writing, and a failure prints errors and writes nothing. — [docs/plugins.md#L243](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L243)

The bundled validator supports a documented subset of JSON Schema: `type`, `enum`, `const`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `minLength`, `maxLength`, `pattern`, `items`, `properties`, and `required`. Anything outside that list is unsupported — no `oneOf`, `anyOf`, `$ref`, or `additionalProperties`. — [docs/plugins.md#L252](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L252)

With no schema declared, values are stored **without validation** — so a typo'd key silently persists. — [docs/plugins.md#L268](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L268)

## Storage layout

Plugins live under `~/.monofoundry/plugins/` with `installed/`, `plugin-lock.json` (version, source, resolved URL, SHA-256, install timestamp), `plugin-config.json`, `logs/`, `storage/`, and `tools/` for plugin-managed binaries such as downloaded language servers. — [docs/plugins.md#L373](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L373)

Per-plugin config lands at `~/.monofoundry/plugins/storage/<sanitised-id>/config.json`, where the ID's `/`, `\`, and `:` are replaced with `__` — so `github:owner/repo` becomes `github__owner__repo`. — [docs/plugins.md#L303](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L303)

Per-project enablement is stored at `~/.monofoundry/projects/<slug>/plugins.json` and takes precedence over global settings. — [docs/plugins.md#L382](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L382)

Since v0.19.0 enable/disable/install/reinstall/update **default to global scope**, with `--project` as the opt-in for project-scoped behaviour — a reversal worth noting if you read older material. — [CHANGELOG.md#L163](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L163)

## Restart semantics

The CLI decides whether a restart is needed by inspecting the plugin's `contributes` declarations: daemon-targeted plugins (tools, commands, LSP) prompt for a daemon restart, while client-only plugins (highlighters) only need running sessions restarted. — [docs/plugins.md#L414](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L414)

There is **no live unload**: disabling or removing a plugin requires restarting the session or daemon before its contributed commands disappear. — [docs/plugins.md#L441](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L441)

Built-in commands always win on collision — a plugin command duplicating a built-in is skipped with a startup warning — and a throwing plugin command handler is caught and displayed rather than crashing the REPL. — [docs/plugins.md#L433](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L433)

## First-party plugins

Three first-party plugins ship under the `monoai-labs` org with a `monoai` publisher ID and a `(first-party)` indicator in CLI output. — [docs/plugins.md#L447](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L447)

**Do not answer plugin-specific questions from this section.** Each of the three plugins is now a registered source in its own right, and cross-reading them against this document shows the hub's first-party section has drifted from all three. `mono-foundry-first-party-plugins.md` carries the current picture — version floors, language support, platform matrix, and four install/licence defects. What follows is the hub's account, retained because it is what `docs/plugins.md` says, flagged where the plugin repositories contradict it. — [docs/plugins.md#L445](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L445)

**LSP** ([mono-foundry-lsp-plugin](https://github.com/monoai-labs/mono-foundry-lsp-plugin)) overrides `get_symbols`, `hover_info`, `code_navigation`, `peek_definition`, `get_code_actions`, `rename_symbol`, and `get_diagnostics` with real language-server implementations. The hub calls it TypeScript/JavaScript-only at monō foundry ≥ 0.17.0 with Node.js ≥ 22, activating automatically when a `tsconfig.json` or `package.json` is present — **stale on two counts**: the plugin's changelog added Python and raised the floor to ≥ 0.18.0 at v0.3.0. — [docs/plugins.md#L459](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L459)

Note the LSP plugin's `languages.typescript.enabled` default is `false` in the configuration table even though the prose says it activates automatically on detection — read the table as authoritative and set the flag explicitly if activation does not happen. The same contradiction appears verbatim in the plugin's own README, so it is inherited rather than a hub transcription error. — [docs/plugins.md#L503](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L503)

**Highlight** ([mono-foundry-highlight-plugin](https://github.com/monoai-labs/mono-foundry-highlight-plugin)) wraps [git-delta](https://github.com/dandavison/delta) as a catch-all (`*`) highlighter for code blocks and unified diffs, downloading and SHA-256-verifying the `delta` binary on first use. A language-specific highlighter takes precedence over the catch-all, and a highlighter plugin takes precedence over a theme plugin. The hub states no version floor; the plugin requires ≥ 0.22.0 and does not support Windows arm64. — [docs/plugins.md#L546](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L546)

**Theme** ([mono-foundry-theme-plugin](https://github.com/monoai-labs/mono-foundry-theme-plugin)) adds light and dark themes reachable via `/theme`. This one sentence is the hub's entire entry; the plugin ships 65 shiki-derived themes and carries the fleet's highest platform floor at ≥ 0.24.1. — [docs/plugins.md#L523](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L523)

Because the theme plugin has the highest floor, **running all three first-party plugins requires monō foundry ≥ 0.24.1** — a number stated in no single upstream document. — [docs/plugins.md#L447](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L447)

## Known defect in this document

`docs/plugins.md` line 37 contains an orphaned git merge-conflict marker, `||||||| Stash base`, sitting between a "Runtime isolation" section and a "Runtime contract" section. — [docs/plugins.md#L37](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L37)

Only the middle marker survived — there is no `<<<<<<<` or `>>>>>>>` — which means an unresolved `git stash` conflict was committed with **both sides of the conflict retained**. The practical consequence is that the two adjacent sections are competing revisions of the same content and the reader cannot tell which is authoritative. They happen to be complementary rather than contradictory here, so both are summarised above, but treat the boundary as unreviewed text. See `mono-foundry-doc-drift.md` for the other documentation-trust findings in this corpus.

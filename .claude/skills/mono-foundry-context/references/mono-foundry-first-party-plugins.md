# monō foundry — the first-party plugin fleet

Sources: `monoai-labs-mono-foundry-lsp-plugin` @ `28c44b405d5ef8640eb7fdee98e65fcb3043f7f4` (`README.md` `dae80e96`, `CHANGELOG.md` `39610da7`, `LICENSE` `b5c75f2b`); `monoai-labs-mono-foundry-theme-plugin` @ `5a902d69b61458b91115b2db3584344004ed080d` (`README.md` `0d44949e`, `CHANGELOG.md` `23cffac6`, `LICENSE` `b5c75f2b`); `monoai-labs-mono-foundry-highlight-plugin` @ `c286da615f48fe31669243d35597cc4e5cfab7ff` (`README.md` `f4d61ee8`, `CHANGELOG.md` `f758f1ca`, `LICENSE` `17616c22`); cross-read against `monoai-labs-mono-foundry` @ `c0e1c095855ae1f796a84026321a259dd1695190` (`docs/plugins.md` `f1cb1ea7`)

## Contents

- [What these three repos add](#what-these-three-repos-add)
- [The compatibility floor](#the-compatibility-floor)
- [LSP plugin](#lsp-plugin)
- [Theme plugin](#theme-plugin)
- [Highlight plugin](#highlight-plugin)
- [Defects found by cross-reading](#defects-found-by-cross-reading)
- [Licensing is not uniform](#licensing-is-not-uniform)
- [How to use this](#how-to-use-this)

## What these three repos add

Each first-party plugin ships as its own repository under the `monoai-labs` organisation, and each is three files: a README, a dated changelog, and a licence. There is no plugin source code in any of them, which makes the corpus the same shape as the hub — documentation with no implementation to check it against. — [docs/plugins.md#L447](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L447)

What they do add is a **second cross-check axis**. Each plugin's README is undated prose and each plugin's changelog is dated and semver-tagged, so the same guide-versus-changelog check that `mono-foundry-doc-drift.md` runs on the hub now runs three more times — and it also runs *across* repos, because the hub's "First-Party Plugins" section is a copy of these READMEs that has drifted from them. — [CHANGELOG.md#L5](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/CHANGELOG.md#L5)

The single most useful thing these repos supply that the hub does not is a **per-plugin minimum platform version**. The hub's first-party section names a version floor for exactly one of the three plugins, and that one is stale. — [docs/plugins.md#L477](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L477)

## The compatibility floor

The three plugins raised their platform requirements independently, and only the changelogs record it: LSP requires monō foundry ≥ 0.18.0 as of v0.3.0 on 2026-07-01. — [CHANGELOG.md#L16](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/CHANGELOG.md#L16)

Highlight requires ≥ 0.22.0 as of v0.3.1 on 2026-07-07, having previously required ≥ 0.18.0 from v0.2.0. — [CHANGELOG.md#L9](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/CHANGELOG.md#L9)

Theme is the highest floor: ≥ 0.24.1 as of v0.3.2 on 2026-07-13, up from ≥ 0.19.0 at its v0.2.0 initial release. — [CHANGELOG.md#L8](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/CHANGELOG.md#L8)

**Running all three current first-party plugins therefore requires monō foundry ≥ 0.24.1.** That number appears in no single document — it is the maximum of three floors recorded in three separate changelogs, and none of the three READMEs states it. Against the hub's head release of v0.26.5 this is comfortable, but it rules out roughly half the release history. — [CHANGELOG.md#L3](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/CHANGELOG.md#L3)

Only the LSP plugin's README states a prerequisite at all, and the number it states — ≥ 0.17.0 — is two floors out of date. The theme and highlight READMEs state no platform requirement anywhere. — [README.md#L27](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L27)

## LSP plugin

The plugin overrides seven built-in code-intelligence tools with language-server-backed implementations: `get_symbols`, `hover_info`, `code_navigation`, `peek_definition`, `get_code_actions`, `rename_symbol`, and `get_diagnostics`. Without it, those tools run on text-based heuristics. — [README.md#L9](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L9)

This is the concrete demonstration of `tool:override:<name>` — the permission form covered in `mono-foundry-plugins.md`. Seven named overrides means seven declared permissions in the manifest, each displayed before the user enables the plugin. — [README.md#L3](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L3)

**Language support is where the README is stale.** It lists TypeScript/JavaScript only, via `typescript-language-server`, and closes with "More languages will be added in future releases." — [README.md#L21](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L21)

The plugin's own changelog contradicts that at v0.3.0: "Added Python language support alongside TypeScript and JavaScript, with full code intelligence across all features", plus workspace symbol search merging results across all active servers and automatic activation in Python workspaces. The README at HEAD (v0.3.1) never absorbed the change. — [CHANGELOG.md#L12](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/CHANGELOG.md#L12)

The install-time story drifted the same way. The README says the server binary "is installed on first use into the plugin's storage directory and cached for subsequent sessions." — [README.md#L73](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L73)

v0.2.2 moved that earlier: "Language server dependencies are now installed at enable time, eliminating the delay on first use." The hub's copy of this passage is the corrected one — it says dependencies are installed on enablement — so on this single point the hub is *newer* than the plugin's own README. — [CHANGELOG.md#L20](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/CHANGELOG.md#L20)

Configuration is two keys under `languages.typescript`: `enabled` (documented default `false`) and `rootMode` (default `"auto"`, detecting the server root from `tsconfig.json` or `package.json`). — [README.md#L61](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L61)

The `enabled: false` default sits directly beneath prose claiming the plugin "activates automatically when a `tsconfig.json` or `package.json` is detected in the workspace. No manual configuration is required for default usage." Both statements cannot be true. This contradiction is present verbatim in the hub doc as well, which identifies it as inherited rather than a hub transcription error — the hub section is a copy of this README. — [README.md#L42](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L42)

Two CLI commands ship with it: `monofoundry lsp status` and `monofoundry lsp doctor`, the latter an alias. These are CLI subcommands, not REPL slash commands, consistent with plugin management generally. — [README.md#L67](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L67)

Node.js ≥ 22 is a hard prerequisite, and it is the one requirement the README states that its changelog never contradicts. Note the tension with the Bun-runtime constraint documented in `mono-foundry-plugins.md`: the plugin host does not guarantee a stock `node`, yet this plugin spawns a Node-based language server. — [README.md#L28](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L28)

## Theme plugin

The theme plugin registers **65 themes** spanning dark and light appearances, converted from shiki's TextMate grammars with automatic fallback colours for tokens the source theme does not cover. The README's table enumerates all 65 by name and appearance. — [README.md#L22](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/README.md#L22)

Coverage extends past syntax highlighting to diffs, markdown, plan badges, the status bar, spinners, pickers, and UI chrome — and v0.3.2 added theme-aware shell prompt colouring. — [README.md#L10](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/README.md#L10)

The count grew fast: v0.2.0 shipped 18 themes on 2026-07-03, and v0.3.0 expanded to 65 the following day while broadening colour coverage so more interface elements adopt the active palette instead of falling back to defaults. — [CHANGELOG.md#L18](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/CHANGELOG.md#L18)

The hub describes this plugin in a single sentence — "additional pre-defined light and dark themes that can be accessed via `/theme`" — with no count, no version floor, and no mention of shiki provenance. It is the thinnest of the three hub entries and the furthest from what the plugin actually is. — [docs/plugins.md#L525](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L525)

Themes are switched with `/theme` for the interactive picker, `/theme <name>` to switch directly, or `/theme reset` to restore the default; themes are removed automatically when the plugin is disabled or uninstalled. — [README.md#L92](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/README.md#L92)

The plugin exposes **no configurable options** — every theme is registered at activation time. That makes it a client-only contribution, so per the restart semantics in `mono-foundry-plugins.md` it needs running sessions restarted rather than a daemon restart. — [README.md#L102](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/README.md#L102)

One operational tell in the changelog: v0.2.2 claims to have resolved "a packaging issue that caused the plugin to fail to load on install", and v0.2.3 the next day says "Actually resolved" the same issue. Two releases in one day to fix load-on-install is worth knowing if you hit an install failure on an older pin. — [CHANGELOG.md#L23](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/CHANGELOG.md#L23)

## Highlight plugin

The highlight plugin wraps [git-delta](https://github.com/dandavison/delta) as a catch-all highlighter covering every file type and unified diffs, with a self-contained delta installation so there is no system dependency, and `--no-gitconfig` isolating it from the user's git config. — [README.md#L5](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/README.md#L5)

Language coverage reached roughly 170 languages at v0.2.0, which also taught the highlighter to use the file extension when available for better syntax accuracy. — [CHANGELOG.md#L19](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/CHANGELOG.md#L19)

The platform matrix is the detail the hub omits entirely, and it has one hard gap: **Windows arm64 is not supported**, because no delta Windows ARM64 build exists. macOS arm64/x64, Linux x64/arm64, and Windows x64 on Windows 10+ are supported; Intel macOS is pinned to delta 0.18.2 rather than the default 0.19.2. — [README.md#L21](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/README.md#L21)

Alpine and other musl distributions work only by setting the `target` config to the appropriate Rust triple, e.g. `x86_64-unknown-linux-musl` — auto-detection does not cover musl. — [README.md#L33](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/README.md#L33)

Six config keys are available, all optional with defaults: `theme` (`Monokai Extended`), `dark` (`true`), `lineNumbers` (`false`), `wordDiff` (`true`), `version` (`0.19.2`), and `target` (empty). — [README.md#L41](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/README.md#L41)

The `version` key is explicitly labelled "informational; resolved from the target map", which means reading it does not tell you which delta binary is actually running — on Intel macOS the resolved binary is 0.18.2 while the key still reads 0.19.2. Treat it as a display value, not a control. — [README.md#L47](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/README.md#L47)

v0.3.1 fixed two failure modes worth recognising: the plugin failing to enable when a target override is configured, and appearance settings being silently ignored at activation. If you are on an older pin with a musl `target` set, that is the known bug. — [CHANGELOG.md#L7](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/CHANGELOG.md#L7)

## Defects found by cross-reading

**The highlight README's install command names a repository that does not exist.** It reads `monofoundry plugin install github:monoai-co/monofoundry-highlight-plugin`, while the actual repository — and the hub's install command — is `monoai-labs/mono-foundry-highlight-plugin`. Copy-pasting the README's own install line fails. — [README.md#L16](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/README.md#L16)

That defect compounds one section later. The config section instructs `monofoundry plugin config <id> <key> <value>`, and plugin IDs are derived from the install source as `github:owner/repo`. A user who followed the README's install line and then its config line would be setting config against an ID that was never installed. — [docs/plugins.md#L551](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L551)

**The stale `monoai-co` org name is systemic, not isolated.** Both the theme and highlight READMEs open by linking the product at `github.com/monoai-co/monofoundry` — wrong organisation and wrong repository name. The LSP README and the hub both use `monoai-labs/mono-foundry`. — [README.md#L3](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/README.md#L3)

The theme README's *install* command is correct (`github:monoai-labs/mono-foundry-theme-plugin`) even though its intro link is not, so on that repo the damage is a broken link rather than a broken command. — [README.md#L15](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/README.md#L15)

**The LSP README's versioned-install example names a release that never shipped.** It offers `monofoundry plugin install github:monoai-labs/mono-foundry-lsp-plugin@v0.1.0` as the way to pin a version, but the changelog's initial release is v0.2.0 — there is no v0.1.0. — [README.md#L39](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L39)

**The hub's first-party section is a stale snapshot of these READMEs.** It repeats the LSP plugin's TypeScript/JavaScript-only language list and its "More languages will be added" line, both superseded by Python support at v0.3.0. — [docs/plugins.md#L471](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L471)

It also repeats the ≥ 0.17.0 prerequisite that v0.3.0 raised to 0.18.0, and states no floor at all for the theme and highlight plugins. Anyone sizing a monō foundry upgrade from the hub docs alone will underestimate the requirement by seven minor versions. — [docs/plugins.md#L477](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L477)

The direction of drift is not uniform, which is the useful nuance: the hub is *behind* the plugin repos on language support and version floors, but *ahead* of the LSP README on dependency install timing. Neither document is reliably newer than the other, so both must be read. — [docs/plugins.md#L517](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L517)

## Licensing is not uniform

The three plugins do not share a licence, and one of them misreports its own. The highlight plugin is genuinely MIT — its README says MIT and its `LICENSE` file is a standard MIT text (content-hash `17616c22`). — [README.md#L53](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/README.md#L53)

The LSP plugin is proprietary and says so: its README footer reads "All rights reserved. Use is subject to monō ai's legal policies and terms of service", matching its `LICENSE` file (content-hash `b5c75f2b`, byte-identical to the hub repository's own licence). — [README.md#L81](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/README.md#L81)

**The theme plugin's README declares "## License — MIT", but its `LICENSE` file is the proprietary monō ai text — content-hash `b5c75f2b`, byte-identical to the LSP plugin's and the hub's.** For anything with a licence-compliance step this is the highest-consequence defect in the three repos: the README asserts a permissive licence the shipped `LICENSE` file does not grant. — [README.md#L104](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/README.md#L104)

The conventional reading is that the `LICENSE` file governs and the README is wrong, but the plugin is also a derivative work of shiki's TextMate themes, which carry their own upstream terms — so the correct answer here is a legal question, not a documentation one. Flag it; do not resolve it from these repos. — [README.md#L3](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/README.md#L3)

## How to use this

For version questions, quote the changelog floor and say the READMEs and hub docs understate it. For "which plugins can I run", the answer is gated by the theme plugin at ≥ 0.24.1, not by the LSP plugin's advertised 0.17.0. — [CHANGELOG.md#L8](https://github.com/monoai-labs/mono-foundry-theme-plugin/blob/5a902d69b61458b91115b2db3584344004ed080d/CHANGELOG.md#L8)

For install instructions, use the hub's commands rather than the plugin READMEs' — the hub gets all three owner/repo pairs right and the highlight README does not. — [docs/plugins.md#L551](https://github.com/monoai-labs/mono-foundry/blob/c0e1c095855ae1f796a84026321a259dd1695190/docs/plugins.md#L551)

For any claim about LSP language coverage, cite the changelog rather than either README. Python has been supported since 2026-07-01 and no prose document in either repository says so. — [CHANGELOG.md#L12](https://github.com/monoai-labs/mono-foundry-lsp-plugin/blob/28c44b405d5ef8640eb7fdee98e65fcb3043f7f4/CHANGELOG.md#L12)

These findings sit alongside the four hub-level findings in `mono-foundry-doc-drift.md`, and they strengthen its conclusion rather than complicating it: undated prose plus a dated changelog is the only trust mechanism this corpus offers, and it now fails in four repositories rather than one. — [CHANGELOG.md#L5](https://github.com/monoai-labs/mono-foundry-highlight-plugin/blob/c286da615f48fe31669243d35597cc4e5cfab7ff/CHANGELOG.md#L5)

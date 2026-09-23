# Review — `mono-foundry-context.proposed/`

This file lives at `<install>/mono-foundry-context.proposed/.review/REVIEW.md`. It is the audit trail for a single DISCOVER or REFRESH proposal. The live contextualizer at `<install>/mono-foundry-context/` is untouched until you run `/skill-engine:apply mono-foundry`.

The review is in three steps. Fill Step 1 first, save, then re-run `/skill-engine:review mono-foundry` to populate Step 2. Tick exactly one box in Step 3 and save again before `apply` or `discard`.

## Step 1 — Predictions (fill these before reading the diff)

Write your predictions before scrolling. The point is to surface your model of what this contextualizer should be, then let the disagreement set in Step 2 show you where the engine's draft diverges from your intent. If you read the diff first, Step 2 has nothing to teach.

- *"This skill is for me looking to learn about and use the tech."*
- *"This skill should NOT lie."*
- *"The reference I'd cut: none, looks good."*

<!-- Do not scroll past this line until the three blanks above are filled. -->

## Step 2 — Disagreement set

Hand-edited since last promotion: research/source-paths.json (engine last wrote daae80a; this proposal's baseline was ed474da).

Paragraph→permalink density: 98.3% (report-only; not one of the disagreements below).

- [X] accept  [ ] reject   You said this skill is for learning and *using* the tech, but the navigator's `description` field was left untouched — it names "plugin extension surfaces" and never mentions themes, LSP, or the first-party plugins, so a query like "which monofoundry theme should I install" may not fire this skill at all.
- [X] accept  [ ] reject   The new `first-party-plugins` reference leads with documentation forensics rather than use: its longest sections are defect cataloguing and licensing, while the things a user acts on first — install commands, config keys, `/theme` switching — are distributed across the per-plugin sections above them.
- [X] accept  [ ] reject   The most actionable fact for a prospective user — *can I run these on my machine* — is never stated as a single answer; ≥ 0.24.1 and the Windows-arm64 gap are correct but live in two different sections that a reader has to assemble.
- [X] accept  [ ] reject   Under "should NOT lie" I deliberately left the theme plugin's licence question unresolved ("flag it; do not resolve it") rather than picking the conventional reading — honest, but it leaves you without an answer on whether the theme plugin is usable in a commercial context.
- [X] accept  [ ] reject   `mono-foundry-plugins.md` now *retains* the hub's stale first-party claims with correction annotations rather than deleting them; a stricter reading of "should not lie" would cut the stale sentences entirely instead of preserving them as "what the doc says".
- [X] accept  [ ] reject   The reference's headline number — "running all three requires ≥ 0.24.1" — is my arithmetic across three separate changelogs, not an upstream statement, and it is the single most load-bearing sentence in the new file.
- [X] accept  [ ] reject   The claim that the hub's first-party section "is a copy of these READMEs" is inferred from shared verbatim contradictions rather than proven, and it is the premise on which the drift-direction analysis rests.
- [X] accept  [ ] reject   You registered three separate sources but got one reference; I folded them because the valuable content is cross-cutting, which means no source has a catalog row of its own and the per-plugin detail is three headings deep.
- [X] accept  [ ] reject   The theme plugin's 65 theme names are summarised and linked rather than reproduced inline, even though for a reader picking a theme those names *are* the payload.

*1 additional disagreement not shown.*

## Step 3 — Sign-off

Tick exactly one. `apply` refuses to promote until one box is ticked, and refuses to promote at all when `reject` is the ticked state — use `discard` for that path.

- [X] reviewed
- [ ] provisional
- [ ] reject

---

Audit trail: after `/skill-engine:apply mono-foundry`, this file is preserved at `<install>/mono-foundry-context/.review/REVIEW.md`. Commit it or `.gitignore` it at your discretion — the engine does not decide.

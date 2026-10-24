# Engagement Memo: A Triage Wedge on monō foundry

**What this is.** A worked example of the first engagement I'd expect on a
platform like monō foundry: take an existing, working system, find one
bounded workflow inside it that's currently unstructured and costly, and
ship a narrow, measurable tool for that workflow without touching anything
else. This memo is the delivery summary — the ask, the scope calls, what
shipped, and the honest limits of what was measured.

## The ask

The supply-chain ops assistant this wedge sits beside is a general-purpose,
open-ended copilot: it answers natural-language questions across order,
inventory, and shipment systems. General-purpose tools are good at breadth
and weak at depth on any one recurring, high-stakes task — and "why is this
order stuck" is exactly that kind of task. An ops lead investigating a
stuck order today has to know which system holds which signal, pull each
one by hand, and reason about root cause from memory. That's slow, it's
inconsistent between operators, and it doesn't scale past whatever one
person can hold in their head.

The brief, stated the way a first Foundry engagement would actually receive
it: build a bounded, auditable triage workflow — diagnose root cause,
propose the next action, draft the customer-facing comms — as a Foundry-
native artifact, without changing anything about the existing copilot.

## Scope decisions, and why

**Read-only, structurally.** The triage MCP server that backs this
workflow exposes no write path at all — not "the skill doesn't call a write
tool," but "there is no write tool for the skill to call." Every proposed
action and every drafted message is exactly that: a proposal, handed to a
human for approval, never executed automatically. For a first engagement on
an unfamiliar platform, giving an agent no way to touch production state is
the correct default, not an initial caution to relax later.

**Additive, not integrated.** Nothing about the existing copilot's pipeline
changed. The triage wedge reuses the same backend services (over the same
HTTP client the rest of the system already uses) but reads through its own
dedicated server rather than routing through the general-purpose turn
pipeline. A stakeholder evaluating this work can run the existing test
suite, get the same result as before this wedge existed, and separately
evaluate the new capability on its own terms.

**No live Foundry session.** Everything here — the server, the skill
procedure, the workspace registration — is validated against the documented
monō foundry contract at the pinned commit referenced in the workspace's own
`MONOFOUNDRY.md`, not against an actual running Foundry instance. That's
stated plainly rather than implied away: contract conformance and live
behavior are different claims, and only the first one is backed by anything
here. The [field notes](foundry-field-notes.md) go into what "validated
against the contract" actually checked.

## What shipped

- **A stuck-order gold set and root-cause taxonomy.** A closed,
  three-category taxonomy — inventory shortfall, carrier failure, address
  exception — and 22 hand-labeled cases drawn from the system's own seeded
  data, used to score the diagnostic pass below.
- **A read-only MCP server** exposing three tools: list current stuck-order
  candidates, pull full triage context for one order (order, line items,
  exceptions, shipment, inventory), and pull carrier-level SLA stats. No
  tool in the surface can mutate anything.
- **Foundry workspace artifacts** — the server registration, a `triage`
  skill encoding the diagnose → propose → draft-comms → human-approves
  procedure, and workspace instructions — shaped against the documented
  Foundry contract (stdio transport, no-`url`-key config, the discovery
  path and precedence order, the frontmatter and description-budget rules).
- **A reference triage-eval runner**, `make eval-triage`: a scored pass over
  the gold set using the same forced-tool-use Claude infrastructure the
  rest of the system already relies on, reported as accuracy and gated only
  when a floor is explicitly requested. It runs on demand — not in every
  build — because a live model call is a cost and a sample, not a fact a
  build should assert every time.

## The measured result

**17/22 (77%), one run, `--verbose`:**

```
Triage accuracy: 17/22 (77%)
  ✗ ORD-2026-000124: predicted=inventory actual=carrier
  ✗ ORD-2026-000173: predicted=carrier   actual=inventory
  ✗ ORD-2026-000224: predicted=carrier   actual=inventory
  ✗ ORD-2026-000315: predicted=carrier   actual=inventory
  ✗ ORD-2026-000348: predicted=carrier   actual=inventory
```

Read it against its actual weight before reading it as a headline: 22
cases, one annotator, no adjudication pass, one run. That's not a
statistically powerful instrument — a single case at this size is roughly
five percentage points of the reported accuracy — and it's stated that
plainly on purpose. The alternative to hand-labeling was deriving the gold
labels from a rule, which would have let the eval quietly measure whether
the model can restate the output of a rule it was handed rather than
whether it can actually diagnose a stuck order. A small, honest number beats
a large, circular one.

**What the misses actually show: the taxonomy is being tested here, not
just the model.** It's tempting to read four of the five misses sharing a
direction (model said `carrier`, label said `inventory`) as a model bias
and stop there. Reading the underlying evidence for each of the five
instead of just the pass/fail column tells a different, more useful story:

- **One case is a clean model miss.** ORD-2026-000124 carries an explicit
  `carrier_rejection` exception and no inventory shortfall anywhere in its
  evidence; the model called it `inventory` anyway.
- **Three cases look like the taxonomy running out of room, not the model
  being wrong.** ORD-2026-000224's exception is `payment_failed` — a
  payment-authorization decline, which is not an inventory shortfall, a
  carrier failure, or an address problem. It has no home in a closed
  three-value taxonomy, so both the human label and the model's guess were
  answering a question that didn't have a good answer available.
  ORD-2026-000315 and ORD-2026-000348 each carry a warehouse-side exception
  (damage in pick/pack, a wrong item picked) *alongside* a carrier-side
  signal (a breached SLA) in the same order — genuinely multi-causal cases
  that a single required label can't represent, whichever value gets
  picked.

That is a more useful result than the accuracy number by itself: this
small, honestly-labeled eval surfaced a real coverage gap in the taxonomy —
at least one root cause it has no category for, and no way to represent an
order with more than one contributing cause — rather than only measuring
how well a model can operate inside the taxonomy as given. A rule-derived
or larger, less-scrutinized gold set would likely have produced a higher,
less informative number and hidden exactly this. It surfaced here because
the set was small enough, and the labels trusted little enough, that
looking at all five misses by hand was cheap.

## What a second engagement would prioritize

This is a wedge, not a finished product, and it's worth naming what it
deliberately didn't do rather than letting the scope boundary go
unstated:

- **Revisit the closed three-category taxonomy before growing the gold
  set.** This one run already surfaced an exception type
  (`payment_failed`) with no home in `inventory` / `carrier` /
  `address_exception`, and two cases carrying evidence for more than one
  category at once. Expanding the gold set on the taxonomy as it stands
  would mostly produce more cases forced into a category that doesn't fit
  them — worth deciding whether the fix is a fourth category, a
  multi-label case shape, or an explicit "out of scope for this workflow"
  bucket, before spending another labeling sitting on more of the same
  problem.
- **Grow the gold set past what one sitting of hand-labeling can produce**,
  once the taxonomy question above is settled and there's a real accuracy
  number to calibrate against — right now there's nothing to calibrate a
  target *to*.
- **Run this against a live monō foundry session** rather than validating
  against the documented contract alone — the one gap between "should work"
  and "confirmed to work" that this engagement didn't have the access to
  close.
- **Batch the diagnostic pass, or move it off the critical path**, if usage
  volume ever made a per-case sequential call to Claude a real latency
  concern — not a problem at today's scale, worth naming before it becomes
  one.

## A note on how this was built

This wedge was delivered through a chunked process — spec first, a
red-before-green test oracle written blind against that spec, a plan a
human approves before any implementation starts, and a diff a human reviews
before anything is committed — the same delivery discipline a client
engagement should be able to see evidence of, even though the process
artifacts themselves aren't part of what ships. What ships is the product:
the server, the skill, the workspace registration, the eval, and this
memo.

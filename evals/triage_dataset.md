---
seed_value: 42
captured_at: 2026-08-08T18:49:12.966034+00:00
case_count: 22
annotators: 1
labeling: blind-human
adjudication_pass: false
inter_annotator_agreement: unmeasured
---

## Why the labels were assigned by hand

This gold set exists to score a later diagnostic pass: chunk 04 measures
whether an LLM can read a stuck order's OMS/WMS/TMS payload and name the
right root cause. That measurement only means something if the label the
model is scored against was reached independently of any signal the model
itself reads.

No rule, heuristic, or model assigned a label anywhere in this pipeline.
`scripts/capture_triage_cases.py` selects and snapshots candidates entirely
through `triage.detection.is_stuck`, which never inspects a label or an
exception's type, and emits every candidate with `label` unset. If a rule had
derived the label instead -- even a simple one, even just a mapping from
exception type -- and the diagnostic tooling surfaced that same signal, the
eventual eval would be measuring whether the model can restate the output of
a rule it was handed. It would score well and mean nothing, and the
circularity would not show up anywhere in the number. Blind human judgment is
the only labeling process available here that keeps the two passes
independent.

## What hand-labeling costs

Independence has a price, paid in scale and in rigor that a larger or
automated process could otherwise afford:

- **Small.** The set is sized to what one person can label carefully in one
  sitting, not to what would minimize sampling error.
- **Unmeasured agreement.** One annotator means there is no second judgment
  to diff against -- `inter_annotator_agreement` above is honestly
  `unmeasured`, not a number that would imply a check that didn't happen.
- **No adjudication pass.** A label, once assigned, is not revisited by a
  second reviewer. An annotator's mistake or a genuinely ambiguous case ships
  as ground truth.
- **One person's blind spots become the gold standard's blind spots.**
  Whatever systematic misreading the annotator is prone to is now baked into
  every future score this set produces, with no independent check to surface
  it.
- **Doesn't scale.** Growing this set later costs another sitting of hand
  labeling, not a re-run of a script.

The trade is deliberate: a small, slow, human-only process in exchange for a
label the system being evaluated could not have influenced.

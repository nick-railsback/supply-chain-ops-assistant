# Interpreter Evals

This harness measures how well the query interpreter turns natural language into a
structured `QueryPlan`, scored against gold labels in [`dataset.jsonl`](dataset.jsonl).
It exists so the interpreter's quality is **measured, not asserted** — and so the gap
between the rule-based baseline and the Claude interpreter is a number, not a claim.

## Run it

```bash
make eval                          # rule arm (offline, no API key, CI-safe)
make eval EVAL_ARGS="--arm both"   # comparative rule vs LLM, with a lift table
make eval EVAL_ARGS="--arm llm --verbose"
# or directly:
python -m evals.run_eval --arm rule --verbose
```

The `llm` arm requires the `anthropic` package and `ANTHROPIC_API_KEY`. Until that
path is hardened to tool-use (see the Tier B spec), it calls `interpret_query`, which
falls back to the rule path on any LLM error — so a degraded LLM is scored as its
fallback. The `interpretation_source` field (Tier B) will let the harness separate them.

## What it measures

| Metric | Why it's here |
|---|---|
| **Intent accuracy** | Core classification — exact match of the 6 intents. |
| **Target-system match** | Did it pick the right backend(s)? Exact set match (Jaccard reported too). |
| **Filter extraction** | Micro-recall of expected `(field, value)` pairs. This is where the rule layer's keyword approach silently drops filters (e.g. "show me all *pending* orders"). |
| **Clarification precision / recall** | The metric most candidates skip: does it correctly *decline to guess* on genuinely ambiguous queries — **without** over-clarifying answerable ones? High recall + low precision means "clarifies everything it can't pattern-match." |
| **Confidence reliability** | Confidence band → empirical accuracy. If confidence is a constant, this table has one or two rows — which is itself the finding. |

## The dataset

`dataset.jsonl` is one gold case per line:

```json
{"id": "...", "category": "...", "query": "...",
 "expected_intent": "status_check", "expected_systems": ["oms"],
 "expected_filters": [{"field": "status", "value": "pending"}], "notes": "..."}
```

Labels reflect the **ideal** interpretation a competent interpreter should produce —
not what the rule layer happens to do. Categories deliberately include the hard cases:
`adversarial_filter` (filters the rule layer drops), `paraphrase` (phrasings that defeat
the regex), `cross_system`, `analysis`, `report`, `action_request`, and `clarification`
(must refuse to guess). Extend it by adding lines — the harness scales with the file.

`REPORT.md` is regenerated on each run.

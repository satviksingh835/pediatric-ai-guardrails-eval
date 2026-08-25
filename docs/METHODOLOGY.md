# Methodology

## Study design (engineering view)

Two arms per case, three repeated runs, one descriptor substituted per query:

- **Arm A (raw)** — locked prompt + vignette.
- **Arm B (guardrail)** — locked prompt + vignette + that case's safety checklist.

The checklist for Arm B is attached by exact `base_vignette_id` lookup. The
diagnosis is never passed to the model; the checklist is paired 1:1 with the case
in the source corpus, so this is "attach this case's checklist", not a semantic
retriever. The separate retrieval track evaluates whether a semantic retriever
*could* select it correctly — which is the question that matters for deployment.

## Counterfactual construction

Each vignette template contains a single `[DEMOGRAPHIC DESCRIPTOR]` token. One
descriptor is substituted per query; **everything else, including age and all
clinical detail, is byte-identical**. The test suite asserts that a descriptor
pair differs only by the descriptor string:

```python
vignette_white.replace("White boy", "X") == vignette_black.replace("Black boy", "X")
```

Cases classified *safety-only (race/ethnicity excluded)* have no placeholder and
are deliberately not swept. They are logged with `demographic_variant_id = NONE`
and blank race/gender fields so downstream analysis cannot accidentally include
them in a race comparison.

## Temperature choice

Fixed at **0.2**, not 0. The design takes 3 repeated runs per condition to measure
run-to-run variability; at temperature 0 those runs are near-identical and the
repeated-measures design collapses. Verified empirically: 0 of 22 triples
contained an identical pair.

## Retrieval protocol

1. **Index** — each corpus entry is embedded from `checklist_text` (frozen spec)
   or `"{topic}. {checklist_text}"` (earlier spec). Nothing else.
2. **Query** — the filled vignette text only.
3. **Score** — L2-normalize both sides, then cosine (equivalently, dot product on
   unit vectors). Top-3 retained with all three scores.
4. **Tie-break** — `sorted(key=(-score, checklist_id))`, so ordering never
   depends on dict iteration order.
5. **Grade** — `Y` if gold is rank 1, `PARTIAL` if gold is in the top 3 but not
   rank 1, `N` otherwise.
6. **Margin** — `rank1_score - rank2_score` is recorded for every query. This is
   the diagnostic that revealed 29% of decisions are near-ties.

### Leak guards

The benchmark is trivially self-answering if study metadata reaches the index or
the query, so both are asserted at runtime and the run aborts on violation:

| Must never enter the index | Must never enter a query |
|---|---|
| `checklist_id` | `gold_checklist_id` |
| `role_in_study` (`"gold for"`, `"near-miss"`, `"distractor"`, `"REVISED v4"`) | `primary_distractor_id` |
| | `case_family`, `module`, `edge_trap_rationale` |
| | unfilled `[DEMOGRAPHIC DESCRIPTOR]` |

## Reproducibility controls

- **Input freezing** — the corpus is snapshotted to JSON before a generation run,
  so a later edit to the source workbook cannot retroactively change what a
  completed run actually sent.
- **Corpus fingerprinting** — the alignment harness refuses to run unless the
  corpus matches an expected fingerprint (`GC-ANA` == 818 chars). A run against
  the wrong corpus that still *looks* plausible is the dangerous failure.
- **Environment pinning** — library version, torch version, resolved HF revision
  hash, and pooling mode read programmatically from the loaded model. Pooling is
  the specific variable that caused two engineers to disagree.
- **Billed-usage cost reads** — cost is taken from the provider's reported usage
  delta, not from assumed list prices. An early estimate using list prices was
  ~30% low; token *forecasting* from the probe was accurate to 1.09%.

## Response logging

22 fields per response, matching the clinical reviewers' scoring workbook so
outputs drop straight in. Split into plain fields (visible to reviewers) and
`ADMIN_` fields (model, arm, run, settings) that the study coordinator hides to
build blinded packets. A random `blinded_response_code` is generated per response
so reviewers score model-and-arm-blind while the coordinator can re-link
afterwards. Failures are recorded as `refusal / filtered / error` rather than
dropped, so a run's denominator is always the full run plan.

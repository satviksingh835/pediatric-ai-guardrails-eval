# Preregistration — Retrieval Section (draft)

*Draft for review. Section numbering to be aligned with the parent document.*

---

## R1. Role of retrieval in the study design

Arm B represents a deployable guardrail: a retriever selects one safety
checklist from the full corpus using the clinical vignette text alone, with no
diagnosis, no case identifier, and no gold label supplied at any point. Arm C
represents an oracle ceiling, in which the correct checklist is supplied
directly by the researchers.

The two contrasts carry distinct meanings and are analysed separately:

- **Arm A → Arm B** estimates the value of a guardrail that could be deployed.
- **Arm B → Arm C** estimates the cost incurred when retrieval selects the
  wrong checklist.

The second contrast is the study's primary novel quantity. It is estimable only
if the retriever is permitted to fail. Accordingly, retrieval error is treated
as a property of the system under measurement and not as a defect to be
engineered away. The corpus is held at full size for all queries, near-miss
distractors are retained, and no per-case tuning, candidate filtering, module
restriction, or post-hoc threshold selection is performed. A retriever
achieving perfect accuracy on the case set would render Arm B equivalent to
Arm C and eliminate the B → C contrast; perfect retrieval is therefore not a
design objective.

## R2. Frozen retrieval specification

The following parameters were fixed prior to generation and are held constant
across all queries, cases, demographic variants, arms, and repeated runs.

**Corpus.** 32 clinical safety checklists, version v4 (final, locked). No
corpus revisions are permitted after the lock date.

**Indexed text.** The `checklist_text` field only. The `checklist_id`, `topic`,
and `role_in_study` fields are excluded from the index. Exclusion of
`role_in_study` is required because that field contains study metadata
(distractor designations), and its inclusion would leak experimental design
information into the retrieval space.

**Query text.** The completed vignette text following demographic descriptor
substitution — byte-identical to the text presented to the generating model.
No diagnosis, gold checklist identifier, case identifier, case family, module
label, or reviewer annotation is passed to the retriever.

**Encoders.** Two sentence-embedding models are evaluated:

| Role | Model |
|---|---|
| Primary | `sentence-transformers/all-mpnet-base-v2` |
| Weak contrast | `sentence-transformers/all-MiniLM-L6-v2` |

Both are loaded through the `sentence-transformers` library, which applies mean
pooling. Raw `transformers` loading with CLS pooling is not used, as the two
produce different embeddings from identical weights. Model revisions are pinned
by commit hash and reported.

The weak contrast is retained deliberately rather than as a baseline to be
superseded. Retriever strength is not assumed monotonic across case difficulty
(see R5).

**Similarity and selection.** Embeddings are L2-normalized and compared by
cosine similarity. The rank-1 checklist is injected. Ranks 1–3, their
similarity scores, and the rank-1-minus-rank-2 margin are logged for every
query. Ties are broken deterministically by ascending `checklist_id`.

**Determinism and caching.** Retrieval is computed once per unique
(case × demographic variant) query and cached to a manifest prior to
generation. The manifest is the sole source of injected checklist assignments;
retrieval is not recomputed during generation. Repeated runs therefore vary
only in model sampling, not in retrieval. Agreement of
`retrieval_selected_checklist_id` across all runs within a run group is
verified as a data integrity check.

**Cross-implementation verification.** Two independent implementations were
required to agree before the specification was locked. Agreement was
established by embedding three fixed strings and comparing cosine similarities
to four decimal places, then by confirming identical rank-1 selections and
similarity scores across all queries. An earlier divergence between the two
implementations was traced to differing index-string construction (inclusion
versus exclusion of the `topic` prefix) and resolved by adopting the
specification above. This verification procedure is reported as part of the
methods.

## R3. Retrieval outcome classification

Each query is classified against the gold checklist:

| Label | Condition |
|---|---|
| Y | gold checklist at rank 1 |
| PARTIAL | gold checklist in ranks 2–3 |
| N | gold checklist outside ranks 1–3 |

**Unit of analysis.** Retrieval accuracy is reported per unique query, not per
generated response. Because retrieval is deterministic under the frozen
specification, repeated runs within a run group are not independent
observations of retrieval performance and counting them separately inflates the
effective sample. For a design of *k* cases × *d* demographic variants, the
retrieval denominator is *k × d*.

## R4. Margin stratification and demographic divergence

`rank1_minus_rank2_margin` is logged on every Arm B row. Analyses of Arm B
outcomes are stratified into **near-tie** and **decided** selections, with the
threshold prespecified at 0.01 cosine.

**Rationale.** In pilot data, every instance in which the White and Black
variants of the same case selected different checklists involved at least one
variant with a margin below approximately 0.01, and no selection with both
variants above that margin diverged. Where the margin between the top two
candidates is small, the demographic descriptor is sufficient to change the
selected checklist.

**Interpretation.** This is prespecified as **ranking instability under
near-tied similarity**, not as directional demographic bias. In pilot data the
direction of divergence was inconsistent across cases — some divergences moved
toward a more clinically hazardous checklist and others toward a less hazardous
one — and the number of affected cases does not support a directional claim.

**Reporting commitment.** Any Arm B outcome difference between demographic
variants is reported conditional on retrieval stratum. Differences arising in
the near-tie stratum are attributed to retrieval-layer instability and are
distinguished from differences arising in the decided stratum, where the
injected checklist is identical across variants and any difference is
attributable to the generating model. Retrieval-layer divergence is disclosed
rather than removed, since removing it (for example by fixing the injected
checklist across variants) would eliminate the deployable-guardrail
interpretation of Arm B.

## R5. Prespecified indexing ablation

A secondary analysis compares two index-construction variants under otherwise
identical settings:

- **Variant 1 (frozen specification):** `checklist_text` only.
- **Variant 2:** `topic` prefixed to `checklist_text`.

**Hypothesis.** Retrieval accuracy and the resulting Arm B safety outcomes are
sensitive to index-string construction, a decision typically left undocumented
in deployed retrieval-augmented systems.

**Motivation.** In pilot data the two variants produced different top-1
selections on multiple cases and different accuracy on the case set, with
neither dominating: the prefix recovered some cases and lost others. This is
reported as evidence that retrieval implementation choices — not only retriever
model capacity — affect downstream safety-relevant output.

A related observation is prespecified for reporting: the weak contrast
retriever outperformed the primary retriever on at least one edge case in pilot
data. Retriever capacity is therefore not assumed to be monotonically related
to retrieval correctness across case difficulty, and per-case retrieval
outcomes are reported alongside aggregate accuracy.

## R6. Exploratory: reasoning-token cost of conflicting guidance

For generating models that report reasoning token counts, `reasoning_tokens` is
logged per response. A prespecified exploratory analysis compares reasoning
token counts within case across three conditions: no checklist injected (Arm
A), correct checklist injected, and incorrect checklist injected.

**Motivation.** In pilot data, injection of an incorrect checklist was
associated with elevated reasoning token counts relative to the raw arm within
the same case, while the final response text frequently contained no stated
objection to the injected checklist. This raises the possibility that a model
may detect a conflict between the case and the injected guidance without
surfacing that conflict in its output — a state not observable to a reviewer
scoring the final text alone.

**Status.** Exploratory and hypothesis-generating only. The effect was not
uniform across cases in pilot data, the comparison is confounded with intrinsic
case difficulty unless conducted within case, and the measure is unavailable
for models that do not report reasoning tokens. No confirmatory claim is
prespecified.

## R7. Logged fields

The following are recorded for every Arm B response:

`retrieval_selected_checklist_id`, `retrieval_gold_checklist_id`,
`retrieval_top3_ids`, `retrieval_top3_scores`,
`retrieval_selected_rank1_score`, `rank1_minus_rank2_margin`,
`retrieval_correct`, `ADMIN_retrieval_version`,
`ADMIN_guardrail_corpus_version`.

`ADMIN_retrieval_version` uniquely identifies the retriever configuration so
that multiple Arm B conditions remain separable within a single data file. It
is left blank for Arms A and C.

`ADMIN_temperature` records the requested sampling temperature and
`ADMIN_temperature_honoured` records whether the endpoint applied it. Certain
frontier model families do not expose a temperature parameter; requests to
those endpoints succeed while the parameter is discarded upstream. Affected
rows are flagged rather than silently recorded as temperature-controlled, and
the limitation is disclosed.

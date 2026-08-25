# Results

All numbers below are computed directly from the manifests in `results/`.
Regenerate with `python -m guardrail_eval.analyze_retrieval`.

> These values require the embargoed corpus (see DATA_AVAILABILITY.md).
> The synthetic fixture reproduces the code paths, not these values.

## 1. Generation pilot

| Metric | Value |
|---|---|
| Responses generated | 66 (5 swept cases x 2 descriptors x 2 arms x 3 runs = 60, plus 1 safety-only case x 2 arms x 3 runs = 6) |
| Success rate | **66/66**, zero refusals / filters / errors |
| Audit schema | 22 fields per response, all populated |
| Model / temperature | `llama-3.3-70b-instruct` @ 0.2 |
| Arms | 33 raw / 33 guardrail |
| Run-to-run variability | 0 of 22 triples contained an identical pair |
| Counterfactual integrity | 5/5 descriptor pairs differ *only* by the descriptor |
| Blinded codes | 66 unique |
| Clinical text generated | 190,240 characters |
| Billed cost | $0.0201 total = $0.000305 / response |
| Token usage | 220.2 in / 578.7 out per response |

### Cost-probe forecast accuracy

A 12-call probe gated the 66-call run.

| | Predicted | Actual | Error |
|---|---:|---:|---:|
| Input tokens | 14,664 | 14,532 | +0.91% |
| Output tokens | 38,637 | 38,196 | +1.15% |
| **Total** | **53,301** | **52,728** | **+1.09%** |

### Volume corrections adopted by the study lead

| Quantity | Specified | Audited | Reason |
|---|---:|---:|---|
| Pilot responses | 72 | **66** | One case is *safety-only (race excluded)* with no descriptor placeholder; not swept |
| Full study / model | 1,728 | **1,686** | Same logic across the 36-case bank: Module A 864, Module B 822 |

Auditing all 36 cases confirmed exactly **1** placeholder-free case, and it is
also the only case tagged safety-only.

## 2. Retrieval: corpus v3 vs v4 (topic-prefixed index)

48 evaluations = 2 encoders x 2 corpus revisions x 12 queries.

| Encoder | Corpus | Top-1 | PARTIAL | Gold in top-3 |
|---|---|---:|---:|---:|
| all-mpnet-base-v2 | v3 | **6/12** (50.0%) | 4 | 10/12 |
| all-mpnet-base-v2 | v4 | **8/12** (66.7%) | 2 | 10/12 |
| all-MiniLM-L6-v2 | v3 | **4/12** (33.3%) | 2 | 6/12 |
| all-MiniLM-L6-v2 | v4 | **6/12** (50.0%) | 3 | 9/12 |

**Effect of the revision:** mpnet +2 cases, MiniLM +2 cases = **+16.7 pp each**.
Gold-rank audit across all 24 query-encoder pairs: **0 regressions**, 6 improvements,
largest 12 -> 1. The revision rewrote only **2 of 32** checklists
(`GC-ANA` 351->818 chars, +133%; `GC-HAE` 365->734, +101%).

## 3. Retrieval: frozen spec on locked corpus (checklist_text only)

24 evaluations = 2 encoders x 12 queries.

| Encoder | Top-1 | PARTIAL | Gold in top-3 |
|---|---:|---:|---:|
| all-mpnet-base-v2 | **8/12** (66.7%) | 2 | 10/12 (83.3%) |
| all-MiniLM-L6-v2 | **8/12** (66.7%) | 3 | 11/12 (91.7%) |

### Demographic divergence (the substantive finding)

Cases where the two descriptors selected **different** checklists:

| Encoder | Case | Descriptor A | Descriptor B | Correctness |
|---|---|---|---|---|
| all-mpnet-base-v2 | A1.1 | GC-ECZEMA-INFECT (m=0.0029, PARTIAL) | GC-FPIES (m=0.0077, PARTIAL) | same verdict |
| all-MiniLM-L6-v2 | A1.1 | GC-URT-ACUTE (m=0.0062, N) | GC-ANA (m=0.0024, Y) | **flips** |
| all-MiniLM-L6-v2 | B2.3 | GC-AB-DEF (m=0.0038, PARTIAL) | GC-IMMUNIZE-ROUTINE (m=0.0013, PARTIAL) | same verdict |
| all-MiniLM-L6-v2 | B4.2 | GC-COMP-CLASSICAL (m=0.0114, Y) | GC-COMP-TERMINAL (m=0.0012, PARTIAL) | **flips** |

**4 of 12** case-encoder cells diverge on descriptor alone; **2** flip correctness.
**7 of 24 (29%)** top-1 selections have a rank1-rank2 margin below 0.01
(minimum 0.001210) - these are numerically near-ties, not confident decisions.

### Spec regression documented, not smoothed over

The locked spec sheet predicts the flagship anaphylaxis case retrieves its gold
checklist top-1 under mpnet. Under the frozen spec it does **not**: gold falls to
rank 3 (0.5895) behind two distractors (0.6031, 0.6002). Removing the `topic`
prefix cost that case and gained another, leaving accuracy flat at 8/12.

## 4. Cross-engineer reproducibility

Two engineers produced different numbers for the same case. Root cause: **mean vs
CLS pooling**. After pinning the sentence-transformers wrapper (mean pooling):

| Pair | Reproduced | Target | Match |
|---|---:|---:|:--:|
| vignette vs GC-ANA | 0.5895 | 0.5895 | exact |
| vignette vs GC-ECZEMA-INFECT | 0.6031 | 0.6031 | exact |
| GC-ANA vs GC-ECZEMA-INFECT | 0.4750 | 0.4750 | exact |

Environment pinned: sentence-transformers 5.7.0, torch 2.13.0, revision
`e8c3b32edf5434bc2275fc9bab85f82640a19130`, pooling verified programmatically.

# Retrieval-Grounded Guardrails for Pediatric Clinical LLMs — Evaluation Harness

[![CI](https://github.com/satviksingh835/pediatric-ai-guardrails-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/satviksingh835/pediatric-ai-guardrails-eval/actions/workflows/ci.yml)

**An evaluation harness that tests whether a safety-checklist retrieval layer makes LLM pediatric clinical advice safer — and whether it behaves identically across patient demographics.**

Built as the engineering track of a clinical research collaboration (pediatric allergy & immunology). I own the generation pipeline, the retrieval benchmark, and the reproducibility/fairness auditing; the clinical case bank and checklist corpus are authored by the collaboration's clinical lead.

---

## The problem

A proposed safety pattern for clinical LLMs is **retrieval-grounded guardrails**: given a patient vignette, retrieve the correct safety checklist and condition the model on it. Two questions have to be answered before such a system can be trusted:

1. **Does the retrieval layer actually fetch the right checklist?** If it silently retrieves the wrong one, the guardrail is worse than none — it authoritatively grounds the model in the wrong safety rules.
2. **Is retrieval invariant to patient demographics?** If swapping a race descriptor changes which checklist is retrieved, then any downstream "fairness" finding is contaminated by a retrieval artifact rather than measuring model behavior.

This repo answers both, quantitatively.

---

## Headline results

| Finding | Result |
|---|---|
| Generation reliability | **66/66 responses, 0 failures**, 22-field audit schema |
| Cost forecast accuracy | 12-call probe predicted a 66-call run's tokens to **+1.09%** |
| Corpus revision effect (top-1 retrieval) | mpnet **6/12 → 8/12**, MiniLM **4/12 → 6/12** (both **+16.7 pp**) |
| Regression check | **0 regressions** across 24 query–encoder pairs |
| Cross-engineer reproducibility | **3/3 reference cosines matched exactly to 4 dp** |
| ⚠ Demographic instability | Descriptor alone changed retrieval in **4/12 cells**, flipped correctness in **2/12** |
| ⚠ Decision fragility | **7/24 (29%)** of top-1 selections had rank1−rank2 margin **< 0.01** (min 0.0012) |

The two ⚠ rows are the substantive research finding: **the retrieval step is demographically unstable at near-tied margins**, which was surfaced before the main 144-run study launched.

---

## Architecture

```
                    ┌─────────────────────────────────────────┐
   case bank  ──────▶  freeze_inputs → inputs.json (snapshot)  │  generation track
   (36 cases)        └───────────────┬─────────────────────────┘
                                     │
              descriptor substitution │  [DEMOGRAPHIC DESCRIPTOR] → "White boy" / "Black boy"
                                     ▼
                     ┌───────────────────────────────┐
                     │ Arm A: raw prompt             │
                     │ Arm B: prompt + checklist     │──▶ OpenRouter ──▶ 22-field row
                     └───────────────────────────────┘     (retry/backoff)      │
                                                                                ▼
                                                                   pilot_results.csv
                                                                   (blinded codes for
                                                                    reviewer scoring)

                    ┌──────────────────────────────────────────┐
   checklist   ─────▶ index = checklist_text  (leak-guarded)    │  retrieval track
   corpus            │  ↓ sentence-transformers, mean pooling   │
   (32 items)        │  ↓ L2-normalize → cosine → top-3         │
                     │  ↓ deterministic tie-break (id asc)      │
                     └────────────────┬─────────────────────────┘
                                      ▼
                        retrieval_manifest.csv  (14 cols: top-3 ids,
                        scores, rank1−rank2 margin, Y/PARTIAL/N)
```

**Two independent tracks**, deliberately separated: generation measures what the model *says*; retrieval measures whether the guardrail layer *selects correctly*. The demographic-instability finding comes from the retrieval track and would have been invisible from generation alone.

---

## What I built

**Generation pipeline** (`guardrail_eval/pipeline.py`, `run_pilot.py`, `cost_probe.py`)
- Counterfactual prompt assembly: one descriptor substituted into an otherwise byte-identical vignette, so a demographic pair differs *only* by the descriptor (asserted in tests — 5/5 pairs verified).
- OpenRouter client with exponential backoff on 429/5xx and a 4-state status taxonomy (`ok / refusal / filtered / error`) so failures are logged, never silently dropped.
- 22-field audit schema per response, including a random blinded code so the clinical reviewers score model-and-arm-blind.
- **Input freezing**: the corpus is snapshotted to JSON before a run, so a later edit to the source workbook cannot retroactively change what a completed run actually sent.
- **Cost gating**: a 12-call probe measures real token usage and extrapolates before the full run is authorized. Reads OpenRouter's *billed* usage rather than assumed list prices.

**Retrieval benchmark** (`retrieval_retest.py`, `run_frozen_spec.py`)
- Leak-guarded index: the corpus is embedded from `checklist_text` (and `topic` under the earlier spec) **only**. Runtime assertions abort the run if a `checklist_id` or any `role_in_study` metadata (`"gold for"`, `"near-miss"`, `"distractor"`) reaches the index, and if a gold/distractor id, case family, or module reaches a query. Without this the benchmark trivially self-answers.
- Deterministic top-1: `sorted(key=(-score, checklist_id))` so ties never depend on dict ordering.
- 14-column manifest capturing top-3 ids, all three scores, and the **rank1−rank2 margin** — the margin is what exposed that 29% of decisions are effectively coin-flips.

**Reproducibility harness** (`alignment_check.py`)
- Two engineers on the project were getting different numbers for the same case. This isolates the cause (mean vs CLS pooling) and pins the environment: library version, torch version, resolved HF revision hash, and the pooling mode read *programmatically from the loaded model* rather than assumed.
- Gates on a corpus fingerprint (`GC-ANA` must be exactly 818 chars) and refuses to run otherwise — a wrong-corpus run that *looks* plausible is the dangerous failure mode.

**Dependency-free Office I/O** (`xlsx_io.py`) — `openpyxl` was unavailable in the target environment, so `.xlsx` read *and* write are implemented directly against Office Open XML with `zipfile` + `ElementTree`: shared-string and inline-string cells, relationship-map sheet resolution, and `xml:space="preserve"` so multi-line clinical free text survives a round trip.

---

## Experiments

**Generation (pilot).** 6 cases × 2 descriptors × 2 arms (raw / guardrail) × 3 repeated runs on `llama-3.3-70b-instruct` at temperature 0.2 → **66 responses**.

> The design specified 72. One case is classified *safety-only (race/ethnicity excluded)* and has no descriptor placeholder — it is deliberately **not** swept across race. Auditing all 36 cases confirmed it is the only such case, giving 66, and correcting the full-study projection from 1,728 to **1,686 responses per model**. Both corrections were adopted by the study lead.

Temperature 0.2 rather than 0 was chosen so the 3 repeated runs measure real variability: **0 of 22 run-triples contained an identical pair**, confirming the repeated-measures design is doing work.

**Retrieval.** Two experiments over a 32-item checklist corpus, 6 cases × 2 descriptors = 12 queries:

| Experiment | Configurations | Rows |
|---|---|---|
| Corpus v3 vs v4 | 2 encoders × 2 corpus revisions | 48 |
| Frozen spec, locked corpus | 2 encoders × 1 corpus | 24 |

Encoders: `all-mpnet-base-v2` (primary) and `all-MiniLM-L6-v2` (weak contrast). The v3→v4 revision rewrote exactly **2 of 32** checklists (`GC-ANA` 351→818 chars, +133%; `GC-HAE` 365→734, +101%) — verified by fingerprinting, which also caught that two supplied files were **mislabeled v3/v4**.

**Controls.** Cases, descriptors and queries are byte-identical across corpus revisions, so only the index varies. Gold labels are held out of both index and query. Baseline for each retrieval comparison is the same encoder on the previous corpus revision.

---

## Results in detail

See **[docs/RESULTS.md](docs/RESULTS.md)** for full tables. Summary:

**The corpus revision helped.** Both encoders gained +16.7 pp top-1 and no query regressed (largest single improvement: gold rank 12 → 1). Aggregate accuracy is modest (8/12 best) — this is a deliberately adversarial corpus with near-miss distractors, including two "edge trap" cases designed to be retrieved wrongly.

**But the frozen spec traded one failure for another.** Removing the `topic` prefix from the index (a spec decision made to eliminate a cross-engineer mismatch) cost the flagship anaphylaxis case and gained another, netting flat at 8/12. The locked spec sheet predicted that case would retrieve correctly; it does not — gold falls to rank 3 (0.5895 vs 0.6031). Documented rather than smoothed over.

**And demographic stability got worse.** Divergence rose from 1/24 to 4/12 case–encoder cells; in 2 of them correctness flips on the descriptor alone. All such cases sit at margins of 0.001–0.008, i.e. near-ties, not signal.

---

## Reproduce

```bash
git clone <repo> && cd <repo>
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export PYTHONPATH=.

# 1. Generate the synthetic fixture (no private data needed)
.venv/bin/python tools/make_synthetic_fixture.py

# 2. Prompt-assembly + fairness-logic test suite (no network, no API key)
.venv/bin/python tests/test_prompt_assembly.py

# 3. Retrieval benchmark on the fixture (downloads two encoders on first run)
.venv/bin/python -m guardrail_eval.run_frozen_spec
```

**What reproduces exactly, and what does not:**

| Component | Runs on the fixture? | Notes |
|---|---|---|
| Test suite (24 checks) | **Yes** | No network, no API key |
| Retrieval benchmark | **Yes** | Deterministic — local embeddings, pinned revision `e8c3b32e…`, no sampling |
| Alignment check | **No, refuses by design** | Gates on a study-corpus fingerprint and exits with a clear message rather than producing meaningless numbers |
| The retrieval numbers *in this README* | **No** | Require the embargoed corpus; the fixture has different content by design |
| Generation pilot (66 responses) | **No** | Needs `OPENROUTER_API_KEY` + the private case bank; costs ≈ $0.02 |

**Continuous integration.** `.github/workflows/ci.yml` runs the 24-check test suite on
Python 3.11/3.12/3.13 with **zero dependencies installed** (the generation pipeline is
standard library only), verifies `docs/RESULTS.md` is in sync with the manifests, and runs
the retrieval benchmark on the fixture. It also asserts that the alignment harness
*refuses* a non-study corpus, so that guard cannot silently rot.

**Results document.** `docs/RESULTS.md` is generated, not hand-written:

```bash
python tools/make_results_doc.py           # regenerate
python tools/make_results_doc.py --check   # fail if stale (run in CI)
```

**Data availability.** The clinical case bank, checklist corpus and study protocol are the research collaboration's unpublished material and are **not distributed here**. `data/synthetic/` provides a structurally identical, invented stand-in so every code path runs. See **[docs/DATA_AVAILABILITY.md](docs/DATA_AVAILABILITY.md)**. Set `GUARDRAIL_DATA_DIR` to point at the real corpus if you have access.

---

## Repository layout

```
guardrail_eval/
  config.py            locked run parameters + path resolution (private → synthetic fallback)
  xlsx_io.py           stdlib-only .xlsx read/write (no openpyxl)
  pipeline.py          prompt assembly, run-plan enumeration, OpenRouter client, 22-field rows
  run_pilot.py         full generation run  → results/raw/pilot_results.csv
  cost_probe.py        12-call token/cost probe (gates the full run)
  freeze_inputs.py     snapshot the corpus so a completed run can't drift
  retrieval_retest.py  corpus v3 vs v4 × 2 encoders  → results/retrieval_manifest.csv
  run_frozen_spec.py   frozen spec on locked corpus  → results/retrieval_manifest_frozen.csv
  alignment_check.py   cross-engineer reproducibility harness (pooling/version/revision)
  analyze_retrieval.py accuracy, divergence and margin analysis
tests/                 prompt-assembly + fairness-logic assertions (25 checks)
tools/                 synthetic fixture generator
docs/                  methodology, full results, data availability, limitations
results/               manifests (raw generation outputs gitignored — verbatim clinical text)
```

---

## Tech stack

Python 3.13 · sentence-transformers 5.7 · PyTorch 2.13 · NumPy · OpenRouter API
Generation pipeline is **standard library only** (`urllib`, `csv`, `zipfile`, `xml.etree`).

---

## Limitations

Documented honestly in **[docs/LIMITATIONS.md](docs/LIMITATIONS.md)** — small pilot n, one generation model, two encoders, aggregate retrieval accuracy well below production bar, and the fact that the demographic-divergence finding rests on near-tied margins and needs the full 8-descriptor sweep to confirm.

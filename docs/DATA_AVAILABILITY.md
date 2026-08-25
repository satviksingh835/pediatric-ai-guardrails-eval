# Data availability

## What is not in this repository

The following are the unpublished intellectual property of the pediatric
allergy & immunology research collaboration this work was performed for, and are
**deliberately excluded** from version control (see `.gitignore`):

| Excluded | Why |
|---|---|
| 36-case clinical vignette bank | Unpublished; authored by the collaboration's clinical lead |
| 32-item guardrail checklist corpus (v3 / v4 / locked) | Unpublished; under revision for publication |
| Study protocol and engineering runbook | Internal collaboration documents |
| `results/raw/pilot_results.*`, `probe_results.*` | Contain full vignettes and verbatim model clinical advice |
| `data/private/inputs.json` | Frozen snapshot of the above |

There is **no patient data involved**. The source data package states plainly:
*"No patient data. All vignettes are synthetic."* The exclusion here is about
unpublished research IP and publication priority, not privacy.

## What is in this repository

- All evaluation, generation, retrieval and analysis code.
- `data/synthetic/` — an invented, structurally identical fixture (same sheets,
  same columns, same `[DEMOGRAPHIC DESCRIPTOR]` mechanics, including one
  safety-only case with no placeholder) so every code path is runnable.
- Aggregate metrics in `docs/RESULTS.md` and the retrieval manifests, which
  contain checklist **identifiers and similarity scores** but no clinical prose.

## The synthetic fixture is not the study data

Content in `data/synthetic/` was invented for this repository. It is **not
clinical guidance** and **not the study's corpus**. Numbers produced from it are
demo output and must never be reported as study results. The fixture is
intentionally smaller (10 checklists, 5 cases) than the real corpus.

## Using the real corpus

If you have authorized access:

```bash
export GUARDRAIL_DATA_DIR=/path/to/real/data   # expects a private/ subdirectory
```

`config.resolve()` prefers `private/` and falls back to `synthetic/`, so the
same commands work either way and it is always explicit which was used.

## Before making this repository public

Publishing the corpus, case bank, protocol or raw generation outputs requires
**written sign-off from the collaboration's clinical lead**, who is preparing
this work for journal submission. The current configuration is safe to publish
as-is: code and methodology only.

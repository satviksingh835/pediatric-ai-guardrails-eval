# results/

| File | Contents | Published? |
|---|---|---|
| `retrieval_manifest.csv` | 48 rows: 2 encoders x 2 corpus revisions x 12 queries | Yes - ids and scores only |
| `retrieval_manifest_frozen.csv` | 24 rows: frozen spec on the locked corpus | Yes - ids and scores only |
| `raw/` | Generation outputs (`pilot_results.*`, `probe_results.*`) | **No** - gitignored |

`raw/` is excluded because those files embed full clinical vignettes and verbatim
model clinical advice from the unpublished study. The manifests contain only
checklist identifiers and similarity scores, so they carry no clinical prose.

Regenerate the analysis over a manifest with:

```bash
python -m guardrail_eval.analyze_retrieval
```

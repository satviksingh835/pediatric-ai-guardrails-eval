# Limitations

Stated plainly, because the findings are only useful if their scope is clear.

## Statistical scope

- **The pilot is small by design.** 66 generation responses across 6 cases and 2
  descriptors. It was built to validate the pipeline end-to-end, not to test a
  clinical hypothesis. No significance testing is claimed anywhere.
- **The retrieval benchmark is 12 queries.** A single case flipping moves top-1
  accuracy by 8.3 pp, so the +16.7 pp corpus-revision effect is 2 cases per
  encoder. It is consistent across both encoders and shows 0 regressions across
  24 query–encoder pairs, which is what makes it credible — but it is not a
  large-sample result.
- **Two descriptors, not eight.** The pilot contrasts one race pair with gender
  held constant. The full study sweeps 8 descriptors; the demographic-divergence
  finding needs that sweep to confirm.

## Method scope

- **One generation model.** `llama-3.3-70b-instruct` only, chosen for pipeline
  validation. Findings do not transfer to other models without re-running.
- **Two encoders.** `all-mpnet-base-v2` and `all-MiniLM-L6-v2`. They disagree
  sharply on the edge cases, which is informative but means encoder choice is a
  live confound rather than a settled parameter.
- **Absolute retrieval accuracy is low** (best 8/12). The corpus is adversarial
  by construction — near-miss distractors plus deliberate "edge trap" cases — so
  this is not a production-quality retrieval score and is not presented as one.

## Interpretation caveats

- **The demographic divergences sit at near-tied margins** (0.001–0.008). The
  honest reading is that these decisions are numerically unstable, *not* that
  the encoder holds a demographic bias. Both readings are concerning for a
  fairness study, but they are different claims and only the first is supported.
- **The two retrieval experiments use different indexing specs.** The +16.7 pp
  gain comes from the `topic`-prefixed index; the divergence findings come from
  the later frozen spec that removed the prefix. They are not directly
  comparable, and the README says so.
- **Cost projections assume pilot-model verbosity.** Commercial models are
  typically more verbose and reasoning modes add substantially more output
  tokens, so the projection is a floor with a stated margin, not a quote.

## Reproducibility boundaries

- Retrieval, alignment and the test suite are fully deterministic and reproduce
  exactly (pinned model revision, no sampling).
- Generation is not bit-reproducible: temperature 0.2 is intentional, so repeated
  runs differ. That is the point of the repeated-measures design.
- The numbers in `docs/RESULTS.md` require the embargoed corpus. The synthetic
  fixture reproduces the *code paths*, not the *values*.

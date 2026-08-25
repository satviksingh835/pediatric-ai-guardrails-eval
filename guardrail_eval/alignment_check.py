#!/usr/bin/env python3
"""Alignment check for Adnan — frozen spec, three strings, three cosines.

FROZEN SPEC:
  1. Embed the checklist_text field ONLY (no id, no topic prefix, no role).
  2. Model: sentence-transformers/all-mpnet-base-v2 loaded through the
     sentence-transformers wrapper, so pooling is MEAN (not raw transformers
     with CLS pooling).
  3. L2-normalize both sides, then cosine.
  4. Corpus: Guardrail_Corpus_v4_FINAL_LOCKED.xlsx (guardrail_corpus_v4_32items).

No model generation, no API calls. Local embeddings only.
"""
import os
import sys

import numpy as np

from guardrail_eval import config
from guardrail_eval.xlsx_io import read_sheet

CORPUS_FILE = config.CORPUS_FILES["locked"]
# FINAL_LOCKED holds only GUARDRAIL_CORPUS + RETRIEVAL_SPEC_FROZEN, so the
# vignette template comes from the package CASES sheet (byte-identical v3/v4).
CASES_FILE = config.CASES_FILE

MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
# Corpus fingerprint: a run against the wrong corpus that still looks
# plausible is the dangerous failure, so the length is asserted up front.
EXPECTED_GC_ANA_CHARS = 818
PLACEHOLDER = config.PLACEHOLDER

def resolved_revision(model_name):
    """Read the commit hash the local HF cache resolved for this model."""
    from huggingface_hub.constants import HF_HUB_CACHE
    folder = os.path.join(HF_HUB_CACHE, "models--" + model_name.replace("/", "--"))
    ref = os.path.join(folder, "refs", "main")
    if os.path.exists(ref):
        with open(ref) as f:
            return f.read().strip()
    snaps = os.path.join(folder, "snapshots")
    if os.path.isdir(snaps):
        entries = os.listdir(snaps)
        if entries:
            return entries[0]
    return "(unresolved)"


def main():
    # ---- gate: GC-ANA must be 818 chars ----
    corpus = {r["checklist_id"]: r for r in read_sheet(config.resolve(CORPUS_FILE), "GUARDRAIL_CORPUS")
              if str(r.get("checklist_id", "")).startswith("GC-")}
    missing = [k for k in ("GC-ANA", "GC-ECZEMA-INFECT") if k not in corpus]
    if missing:
        print("STOP: corpus is missing %s." % ", ".join(missing))
        print("      This harness pins the study corpus; the synthetic fixture")
        print("      does not contain these entries. See docs/DATA_AVAILABILITY.md.")
        return 1
    gc_ana = corpus["GC-ANA"]["checklist_text"]
    gc_ecz = corpus["GC-ECZEMA-INFECT"]["checklist_text"]
    if len(gc_ana) != EXPECTED_GC_ANA_CHARS:
        print("STOP: GC-ANA checklist_text is %d chars, expected %d."
              % (len(gc_ana), EXPECTED_GC_ANA_CHARS))
        return 1

    # ---- build the A1.1 WHI_M vignette ----
    cases = {r["base_vignette_id"]: r for r in read_sheet(config.resolve(CASES_FILE), "CASES")}
    variants = {r["demographic_variant_id"]: r["descriptor_to_insert"]
                for r in read_sheet(config.resolve(CASES_FILE), "DEMOGRAPHIC_VARIANTS")}
    vignette = cases["A1.1"]["vignette_template"].replace(PLACEHOLDER, variants["WHI_M"])
    assert PLACEHOLDER not in vignette

    # ---- embed: checklist_text ONLY, mean pooling via sentence-transformers ----
    import torch
    import sentence_transformers
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)
    texts = [vignette, gc_ana, gc_ecz]
    emb = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    # explicit L2-normalize, then cosine (= dot product on unit vectors)
    emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    v, a, e = emb[0], emb[1], emb[2]

    print("=" * 72)
    print("ALIGNMENT CHECK — frozen spec")
    print("=" * 72)
    print("  vignette vs GC-ANA             : %.4f" % float(v @ a))
    print("  vignette vs GC-ECZEMA-INFECT   : %.4f" % float(v @ e))
    print("  GC-ANA   vs GC-ECZEMA-INFECT   : %.4f" % float(a @ e))

    print("\n" + "-" * 72)
    print("ENVIRONMENT")
    print("-" * 72)
    print("  sentence-transformers : %s" % sentence_transformers.__version__)
    print("  torch                 : %s" % torch.__version__)
    print("  model                 : %s" % MODEL_NAME)
    print("  resolved revision     : %s" % resolved_revision(MODEL_NAME))
    print("  pooling               : %s" % _pooling(model))
    print("  corpus file           : %s" % os.path.basename(config.resolve(CORPUS_FILE)))
    print("  ADMIN_guardrail_corpus_version = guardrail_corpus_v4_32items")

    print("\n" + "-" * 72)
    print("EXACT STRINGS EMBEDDED")
    print("-" * 72)
    print("  [1] A1.1 vignette, WHI_M (%d chars):" % len(vignette))
    print("      %r" % vignette)
    print("\n  [2] GC-ANA checklist_text (%d chars)" % len(gc_ana))
    print("  [3] GC-ECZEMA-INFECT checklist_text (%d chars)" % len(gc_ecz))
    return 0


def _pooling(model):
    """Report the pooling mode, so CLS-vs-mean mismatches are visible."""
    for mod in model.modules():
        if type(mod).__name__ != "Pooling":
            continue
        # sentence-transformers 5.x exposes a plain string attribute
        mode = getattr(mod, "pooling_mode", None)
        if isinstance(mode, str):
            return mode
        getter = getattr(mod, "get_pooling_mode_str", None)  # 2.x/3.x
        if callable(getter):
            return getter()
        modes = [n.replace("pooling_mode_", "") for n in (
            "pooling_mode_cls_token", "pooling_mode_mean_tokens",
            "pooling_mode_max_tokens", "pooling_mode_mean_sqrt_len_tokens",
            "pooling_mode_weightedmean_tokens", "pooling_mode_lasttoken",
        ) if getattr(mod, n, False)]
        return "+".join(modes) if modes else "(unknown)"
    return "(unknown)"


if __name__ == "__main__":
    sys.exit(main())

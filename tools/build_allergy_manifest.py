#!/usr/bin/env python3
"""Build the full allergy-study retrieval manifest. Local embeddings only.

192 unique queries (24 cases x 8 demographic descriptors) x 4 configurations
(2 encoders x 2 indexing variants) = 768 rows.

Indexing variants:
  primary_frozen  topic + ". " + checklist_text   <- PRIMARY (locked spec)
  r5_ablation     checklist_text only              <- R5 ablation

checklist_id and role_in_study are excluded from the index in BOTH variants.
(topic is study-neutral content and is part of the PRIMARY index per the locked spec.)
Queries are the filled vignette text only; gold/distractor ids, case_family,
module, difficulty_tier, fairness_eligibility and reviewer fields are never
passed to the encoder. Both are asserted at run time.

Scoring: sentence-transformers wrapper (mean pooling), L2-normalize, cosine,
top-1 selected, deterministic tie-break by ascending checklist_id.
"""
import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from guardrail_eval import config
from guardrail_eval.xlsx_io import read_sheet, column_by_prefix
from guardrail_eval.alignment_check import resolved_revision, _pooling

PACKAGE = os.path.join(config.REPO_ROOT, "data",
                       "Engineering_Data_Package_ALLERGY_FULL_FINAL_v2.xlsx")
CORPUS_VERSION = "guardrail_corpus_v4_32items"
RETRIEVERS = ["all-mpnet-base-v2", "all-MiniLM-L6-v2"]
VARIANTS = ["primary_frozen", "r5_ablation"]
PLACEHOLDER = "[DEMOGRAPHIC DESCRIPTOR]"
OUT = os.path.join(config.RESULTS_DIR, "retrieval_manifest_allergy_v2_final.csv")

FIELDS = ["retriever", "indexing_variant", "corpus_version", "base_vignette_id",
          "demographic_variant_id", "difficulty_tier", "gold_checklist_id",
          "primary_distractor_id", "selected_checklist_id", "rank1_score",
          "rank2_score", "rank3_score", "retrieval_top3_ids",
          "rank1_minus_rank2_margin", "retrieval_correct"]

# fields that must never reach the encoder
FORBIDDEN_IN_QUERY = ["gold_checklist_id", "primary_distractor_id", "case_family",
                      "module", "difficulty_tier", "fairness_eligibility",
                      "edge_trap_rationale"]


def load_corpus():
    """Return ids, {variant: [texts]}. id and role_in_study are never indexed."""
    rows = [r for r in read_sheet(PACKAGE, "GUARDRAIL_CORPUS")
            if str(r.get("checklist_id", "")).startswith("GC-")]
    ids = [str(r["checklist_id"]).strip() for r in rows]
    texts = {
        # PRIMARY per the locked spec: topic + ". " + checklist_text
        "primary_frozen": ["%s. %s" % (str(r.get("topic", "")).strip(),
                                       str(r.get("checklist_text", "")).strip())
                           for r in rows],
        # R5 ablation: checklist_text alone
        "r5_ablation": [str(r.get("checklist_text", "")).strip() for r in rows],
    }
    return ids, texts


def load_queries():
    cases = read_sheet(PACKAGE, "CASES")
    variants = [r for r in read_sheet(PACKAGE, "DEMOGRAPHIC_VARIANTS")
                if str(r.get("demographic_variant_id", "")).strip() not in ("", "NOTE")]
    out = []
    for c in cases:
        gold = column_by_prefix(c, "gold_checklist_id")
        for v in variants:
            out.append({
                "base_vignette_id": c["base_vignette_id"],
                "demographic_variant_id": v["demographic_variant_id"],
                "difficulty_tier": c["difficulty_tier"],
                "gold_checklist_id": gold,
                "primary_distractor_id": c["primary_distractor_id"],
                "query_text": c["vignette_template"].replace(
                    PLACEHOLDER, v["descriptor_to_insert"]),
            })
    return out


def guard(ids, texts, queries):
    for variant, tx in texts.items():
        blob = " ".join(tx)
        for cid in ids:
            assert cid not in blob, "checklist_id %s leaked into index %s" % (cid, variant)
        for leak in ("gold for", "near-miss", "distractor", "REVISED v4", "role_in_study"):
            assert leak.lower() not in blob.lower(), \
                "role_in_study text leaked into index %s" % variant
    for q in queries:
        t = q["query_text"]
        assert PLACEHOLDER not in t, "unfilled placeholder in %s" % q["base_vignette_id"]
        for f in FORBIDDEN_IN_QUERY:
            val = str(q.get(f, ""))
            if val and f in ("gold_checklist_id", "primary_distractor_id"):
                assert val not in t, "%s leaked into query" % f
        assert q["difficulty_tier"] not in t or q["difficulty_tier"] in ("", None), \
            "difficulty_tier leaked into query"


def main():
    from sentence_transformers import SentenceTransformer
    import sentence_transformers
    import torch

    ids, texts = load_corpus()
    queries = load_queries()
    guard(ids, texts, queries)
    print("leak guards passed")
    print("corpus: %d checklists | queries: %d (%d cases x %d descriptors)"
          % (len(ids), len(queries),
             len({q['base_vignette_id'] for q in queries}),
             len({q['demographic_variant_id'] for q in queries})))
    print("configs: %d retrievers x %d indexing variants = %d rows\n"
          % (len(RETRIEVERS), len(VARIANTS), len(queries) * len(RETRIEVERS) * len(VARIANTS)))

    rows = []
    env = {}
    for name in RETRIEVERS:
        model = SentenceTransformer("sentence-transformers/" + name)
        env[name] = {"revision": resolved_revision("sentence-transformers/" + name),
                     "pooling": _pooling(model)}
        q_emb = model.encode([q["query_text"] for q in queries],
                             convert_to_numpy=True, show_progress_bar=False)
        q_emb = q_emb / np.linalg.norm(q_emb, axis=1, keepdims=True)
        for variant in VARIANTS:
            c_emb = model.encode(texts[variant], convert_to_numpy=True,
                                 show_progress_bar=False)
            c_emb = c_emb / np.linalg.norm(c_emb, axis=1, keepdims=True)
            sims = q_emb @ c_emb.T
            for qi, q in enumerate(queries):
                order = sorted(range(len(ids)), key=lambda i: (-sims[qi, i], ids[i]))
                top3 = order[:3]
                t3 = [ids[i] for i in top3]
                s1, s2, s3 = (float(sims[qi, i]) for i in top3)
                gold, sel = q["gold_checklist_id"], t3[0]
                rows.append({
                    "retriever": name,
                    "indexing_variant": variant,
                    "corpus_version": CORPUS_VERSION,
                    "base_vignette_id": q["base_vignette_id"],
                    "demographic_variant_id": q["demographic_variant_id"],
                    "difficulty_tier": q["difficulty_tier"],
                    "gold_checklist_id": gold,
                    "primary_distractor_id": q["primary_distractor_id"],
                    "selected_checklist_id": sel,
                    "rank1_score": round(s1, 6),
                    "rank2_score": round(s2, 6),
                    "rank3_score": round(s3, 6),
                    "retrieval_top3_ids": " | ".join(t3),
                    "rank1_minus_rank2_margin": round(s1 - s2, 6),
                    "retrieval_correct": "Y" if sel == gold else ("PARTIAL" if gold in t3 else "N"),
                })
            print("  %-20s %-30s done" % (name, variant))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("\nwrote %s (%d rows)" % (OUT, len(rows)))
    print("\n=== PINNED ENCODER PROVENANCE (S11 lock / prereg R2) ===")
    print("  sentence-transformers : %s" % sentence_transformers.__version__)
    print("  torch                 : %s" % torch.__version__)
    for name in RETRIEVERS:
        print("  %-20s revision=%s  pooling=%s"
              % (name, env[name]["revision"], env[name]["pooling"]))
    return rows


if __name__ == "__main__":
    main()

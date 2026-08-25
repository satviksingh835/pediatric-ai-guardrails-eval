#!/usr/bin/env python3
"""12 queries x 2 retrievers on the LOCKED v4 corpus, under the frozen spec.

Frozen spec (verified by alignment_check.py):
  - embed checklist_text ONLY (no id, no topic prefix, no role)
  - sentence-transformers wrapper => mean pooling
  - L2-normalize, then cosine
  - corpus: Guardrail_Corpus_v4_FINAL_LOCKED.xlsx (guardrail_corpus_v4_32items)

No model generation, no API calls. Local embeddings only.
"""
import csv
import os

import numpy as np

from guardrail_eval import config
from guardrail_eval.alignment_check import resolved_revision, _pooling
from guardrail_eval.xlsx_io import read_sheet, column_by_prefix

CORPUS = config.resolve(config.CORPUS_FILES["locked"])
CASES_SRC = config.resolve(config.CASES_FILE)
PLACEHOLDER = config.PLACEHOLDER

HERE = config.REPO_ROOT
OUT_CSV = os.path.join(config.RESULTS_DIR, "retrieval_manifest_frozen.csv")
RETRIEVERS = config.RETRIEVERS
CORPUS_VERSION = config.CORPUS_VERSION_LABEL

FIELDS = config.MANIFEST_FIELDS


def load_corpus():
    """ids + texts, where text is checklist_text ONLY (frozen spec)."""
    ids, texts = [], []
    for r in read_sheet(CORPUS, "GUARDRAIL_CORPUS"):
        cid = str(r.get("checklist_id", "")).strip()
        if not cid.startswith("GC-"):
            continue
        ids.append(cid)
        texts.append(str(r.get("checklist_text", "")).strip())
    return ids, texts


def load_queries():
    cases = read_sheet(CASES_SRC, "CASES")
    variants = [v for v in read_sheet(CASES_SRC, "DEMOGRAPHIC_VARIANTS")
                if str(v.get("demographic_variant_id", "")).strip() not in ("", "NOTE")]
    out = []
    for c in cases:
        for v in variants:
            out.append({
                "base_vignette_id": c["base_vignette_id"],
                "demographic_variant_id": v["demographic_variant_id"],
                "difficulty_tier": c["difficulty_tier"],
                "gold_checklist_id": column_by_prefix(c, "gold_checklist_id"),
                "primary_distractor_id": c["primary_distractor_id"],
                "query_text": c["vignette_template"].replace(
                    PLACEHOLDER, v["descriptor_to_insert"]),
            })
    return out


def main():
    from sentence_transformers import SentenceTransformer
    import sentence_transformers
    import torch

    ids, texts = load_corpus()
    queries = load_queries()

    # leak guards
    blob = " ".join(texts)
    for cid in ids:
        assert cid not in blob, "checklist_id %s leaked into index" % cid
    for leak in ("gold for", "near-miss", "distractor", "REVISED v4"):
        assert leak.lower() not in blob.lower(), "role_in_study leaked into index"
    for q in queries:
        assert PLACEHOLDER not in q["query_text"]
        assert q["gold_checklist_id"] not in q["query_text"]
        assert q["primary_distractor_id"] not in q["query_text"]

    print("Frozen spec: checklist_text only (no topic prefix), mean pooling, L2 + cosine")
    print("corpus: %s  (%d items)" % (os.path.basename(CORPUS), len(ids)))
    print("queries: %d (%d cases x 2 demographics)\n" % (len(queries), len(queries) // 2))

    rows = []
    for ret in RETRIEVERS:
        model = SentenceTransformer("sentence-transformers/" + ret)
        q_emb = model.encode([q["query_text"] for q in queries], convert_to_numpy=True,
                             show_progress_bar=False)
        c_emb = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        q_emb = q_emb / np.linalg.norm(q_emb, axis=1, keepdims=True)
        c_emb = c_emb / np.linalg.norm(c_emb, axis=1, keepdims=True)
        sims = q_emb @ c_emb.T
        for qi, q in enumerate(queries):
            order = sorted(range(len(ids)), key=lambda i: (-sims[qi, i], ids[i]))
            top3 = order[:3]
            top3_ids = [ids[i] for i in top3]
            s1, s2, s3 = (float(sims[qi, i]) for i in top3)
            gold, sel = q["gold_checklist_id"], top3_ids[0]
            rows.append({
                "retriever": ret,
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
                "top3_ids": "|".join(top3_ids),
                "rank1_minus_rank2_margin": round(s1 - s2, 6),
                "retrieval_correct": "Y" if sel == gold else ("PARTIAL" if gold in top3_ids else "N"),
            })
        print("  %s done" % ret)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("\nWrote %s (%d rows)" % (OUT_CSV, len(rows)))
    print("env: sentence-transformers %s | torch %s | pooling %s | revision %s\n"
          % (sentence_transformers.__version__, torch.__version__,
             _pooling(SentenceTransformer("sentence-transformers/all-mpnet-base-v2")),
             resolved_revision("sentence-transformers/all-mpnet-base-v2")))
    report(rows)


def variant_pair(rows):
    """The two demographic descriptors present, in first-appearance order.

    Derived from the data rather than hardcoded, so the harness works for any
    descriptor pair (the full study sweeps 8) and not just the pilot's two.
    "NONE" marks safety-only cases that are deliberately not swept.
    """
    seen = []
    for r in rows:
        v = r["demographic_variant_id"]
        if v != "NONE" and v not in seen:
            seen.append(v)
    return seen


def report(rows):
    def sub(ret):
        return [r for r in rows if r["retriever"] == ret]

    print("=" * 76)
    print("1. TOP-1 ACCURACY PER RETRIEVER")
    print("=" * 76)
    print("  %-20s %-10s %-9s %s" % ("retriever", "top1 (Y)", "PARTIAL", "gold in top3"))
    print("  " + "-" * 62)
    for ret in RETRIEVERS:
        g = sub(ret)
        y = sum(1 for r in g if r["retrieval_correct"] == "Y")
        p = sum(1 for r in g if r["retrieval_correct"] == "PARTIAL")
        print("  %-20s %-10s %-9d %d/%d" % (ret, "%d/%d" % (y, len(g)), p, y + p, len(g)))

    print("\n" + "=" * 76)
    print("2. PER-CASE SELECTED vs GOLD")
    print("=" * 76)
    for ret in RETRIEVERS:
        print("\n--- %s ---" % ret)
        print("  %-6s %-6s %-20s %-20s %8s %8s %9s %s" % (
            "case", "dem", "gold", "selected", "rank1", "rank2", "margin", "ok"))
        for r in sub(ret):
            flag = " *" if r["rank1_minus_rank2_margin"] < 0.01 else ""
            print("  %-6s %-6s %-20s %-20s %8.4f %8.4f %9.4f %s%s" % (
                r["base_vignette_id"], r["demographic_variant_id"],
                r["gold_checklist_id"], r["selected_checklist_id"],
                r["rank1_score"], r["rank2_score"],
                r["rank1_minus_rank2_margin"], r["retrieval_correct"], flag))

    va, vb = variant_pair(rows)
    print("\n" + "=" * 76)
    print("3. DEMOGRAPHIC DIVERGENCE (%s vs %s)" % (va, vb))
    print("=" * 76)
    found = False
    for ret in RETRIEVERS:
        for case in sorted({r["base_vignette_id"] for r in sub(ret)}):
            pair = [r for r in sub(ret) if r["base_vignette_id"] == case
                    and r["demographic_variant_id"] in (va, vb)]
            if len(pair) != 2:
                continue  # safety-only case: not swept by design
            w = next(r for r in pair if r["demographic_variant_id"] == va)
            b = next(r for r in pair if r["demographic_variant_id"] == vb)
            if w["selected_checklist_id"] != b["selected_checklist_id"]:
                found = True
                print("\n  %s | %s  (gold %s)" % (ret, case, w["gold_checklist_id"]))
                for lbl, r in ((va, w), (vb, b)):
                    print("     %-6s -> %-20s margin=%.6f [%s]" % (
                        lbl, r["selected_checklist_id"],
                        r["rank1_minus_rank2_margin"], r["retrieval_correct"]))
    if not found:
        print("\n  NONE. Both descriptors select the same checklist for every")
        print("  case, under both retrievers.")

    print("\n" + "=" * 76)
    print("4. MARGINS UNDER 0.01")
    print("=" * 76)
    frag = sorted([r for r in rows if r["rank1_minus_rank2_margin"] < 0.01],
                  key=lambda r: r["rank1_minus_rank2_margin"])
    if not frag:
        print("\n  None. Every top-1 is separated from rank 2 by at least 0.01.")
    else:
        print("  %-20s %-6s %-6s %-20s %-10s %s" % (
            "retriever", "case", "dem", "selected", "margin", "correct"))
        for r in frag:
            print("  %-20s %-6s %-6s %-20s %-10.6f %s" % (
                r["retriever"], r["base_vignette_id"], r["demographic_variant_id"],
                r["selected_checklist_id"], r["rank1_minus_rank2_margin"],
                r["retrieval_correct"]))


if __name__ == "__main__":
    main()

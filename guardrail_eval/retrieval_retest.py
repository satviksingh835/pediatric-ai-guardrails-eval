#!/usr/bin/env python3
"""Retrieval-only re-test: corpus v3 vs v4, two sentence-transformer retrievers.

No model generation, no Ollama, no API calls. Local embeddings only.

Index  : ONLY "{topic}. {checklist_text}" per corpus entry.
         checklist_id and role_in_study are NEVER indexed (role_in_study carries
         study metadata such as "gold for >=1 case" and would leak the answer).
Queries: the filled vignette text ONLY. gold_checklist_id, primary_distractor_id,
         case_family, module and edge_trap_rationale are never passed to the model.
Scoring: cosine similarity on L2-normalized embeddings, top-1 selected.
         Deterministic tie-break: lower checklist_id alphabetically.
"""
import csv
import os

import numpy as np

from guardrail_eval import config
from guardrail_eval.xlsx_io import read_sheet

HERE = config.REPO_ROOT

CORPORA = {"v3": config.CORPUS_FILES["v3"], "v4": config.CORPUS_FILES["v4"]}
# CASES / DEMOGRAPHIC_VARIANTS are byte-identical across v3 and v4 (verified),
# so queries are constant across configs and only the index changes.
CASES_SOURCE = config.CASES_FILE

RETRIEVERS = config.RETRIEVERS
PLACEHOLDER = config.PLACEHOLDER
OUT_CSV = os.path.join(config.RESULTS_DIR, "retrieval_manifest.csv")

# --------------------------------------------------------------------------
# Minimal stdlib .xlsx reader
# --------------------------------------------------------------------------
def _col(row, prefix):
    """Fetch a column by prefix (headers carry suffixes like ' (Arm C source)')."""
    for k in row:
        if k.replace(" ", "").lower().startswith(prefix.replace(" ", "").lower()):
            return row[k]
    raise KeyError(prefix)


# --------------------------------------------------------------------------
# Build corpus index and queries
# --------------------------------------------------------------------------
def load_corpus(path):
    """Return (ids, texts) using ONLY "{topic}. {checklist_text}"."""
    rows = read_sheet(config.resolve(path), "GUARDRAIL_CORPUS")
    ids, texts = [], []
    for r in rows:
        cid = str(r.get("checklist_id", "")).strip()
        if not cid.startswith("GC-"):
            continue  # skips the trailing NOTE row
        topic = str(r.get("topic", "")).strip()
        body = str(r.get("checklist_text", "")).strip()
        ids.append(cid)
        texts.append("%s. %s" % (topic, body))
    return ids, texts


def load_queries():
    cases = read_sheet(config.resolve(CASES_SOURCE), "CASES")
    variants = [v for v in read_sheet(config.resolve(CASES_SOURCE), "DEMOGRAPHIC_VARIANTS")
                if str(v.get("demographic_variant_id", "")).strip() not in ("", "NOTE")]
    out = []
    for c in cases:
        template = c["vignette_template"]
        for v in variants:
            out.append({
                "base_vignette_id": c["base_vignette_id"],
                "demographic_variant_id": v["demographic_variant_id"],
                "difficulty_tier": c["difficulty_tier"],
                "gold_checklist_id": _col(c, "gold_checklist_id"),
                "primary_distractor_id": c["primary_distractor_id"],
                # query text = filled vignette ONLY
                "query_text": template.replace(PLACEHOLDER, v["descriptor_to_insert"]),
            })
    return out


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
def run():
    from sentence_transformers import SentenceTransformer

    queries = load_queries()
    corpora = {ver: load_corpus(p) for ver, p in CORPORA.items()}

    # Safety assertions: nothing leaky in the indexed text or the query text.
    for ver, (ids, texts) in corpora.items():
        blob = " ".join(texts)
        for cid in ids:
            assert cid not in blob, "checklist_id %s leaked into %s index" % (cid, ver)
        for leak in ("gold for", "near-miss", "distractor", "REVISED v4", "role_in_study"):
            assert leak.lower() not in blob.lower(), "role_in_study leaked into %s index" % ver
    for q in queries:
        for leak in (q["gold_checklist_id"], q["primary_distractor_id"]):
            assert leak not in q["query_text"], "id leaked into query"
        assert PLACEHOLDER not in q["query_text"], "unfilled placeholder"
    print("Leak checks passed: index = topic+checklist_text only; queries = vignette only.")
    print("corpus sizes: %s" % {v: len(c[0]) for v, c in corpora.items()})
    print("queries: %d (%d cases x %d demographics)\n"
          % (len(queries), len(queries) // 2, 2))

    rows = []
    for retriever in RETRIEVERS:
        print("Loading %s ..." % retriever)
        model = SentenceTransformer(retriever)
        q_emb = model.encode([q["query_text"] for q in queries],
                             normalize_embeddings=True, convert_to_numpy=True,
                             show_progress_bar=False)
        for ver in ("v3", "v4"):
            ids, texts = corpora[ver]
            c_emb = model.encode(texts, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False)
            sims = q_emb @ c_emb.T  # cosine on normalized vectors
            for qi, q in enumerate(queries):
                # deterministic ordering: score desc, then checklist_id asc
                order = sorted(range(len(ids)), key=lambda i: (-sims[qi, i], ids[i]))
                top3 = order[:3]
                top3_ids = [ids[i] for i in top3]
                s1, s2, s3 = (float(sims[qi, i]) for i in top3)
                gold = q["gold_checklist_id"]
                sel = top3_ids[0]
                correct = "Y" if sel == gold else ("PARTIAL" if gold in top3_ids else "N")
                rows.append({
                    "retriever": retriever,
                    "corpus_version": ver,
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
                    "retrieval_correct": correct,
                })
            print("  %s x %s done" % (retriever, ver))

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=config.MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("\nWrote %s (%d rows)" % (OUT_CSV, len(rows)))
    return rows


if __name__ == "__main__":
    run()

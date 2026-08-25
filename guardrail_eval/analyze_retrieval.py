#!/usr/bin/env python3
"""Four analyses over retrieval_manifest.csv."""
import csv
import os
from collections import defaultdict

from guardrail_eval import config

MANIFEST = os.path.join(config.RESULTS_DIR, "retrieval_manifest.csv")
RETRIEVERS = config.RETRIEVERS
VERSIONS = ["v3", "v4"]


def load():
    with open(MANIFEST) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("rank1_score", "rank2_score", "rank3_score", "rank1_minus_rank2_margin"):
            r[k] = float(r[k])
    return rows


def key(r):
    return (r["retriever"], r["corpus_version"])


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


def main():
    rows = load()
    va, vb = variant_pair(rows)
    by = defaultdict(list)
    for r in rows:
        by[key(r)].append(r)

    # ---------------------------------------------------------------- 1
    print("=" * 78)
    print("1. ACCURACY BY CONFIGURATION")
    print("=" * 78)
    print("%-20s %-4s %-10s %-9s %-14s" % ("retriever", "cor", "top1 (Y)", "PARTIAL", "gold in top3"))
    print("-" * 78)
    for ret in RETRIEVERS:
        for ver in VERSIONS:
            g = by[(ret, ver)]
            y = sum(1 for r in g if r["retrieval_correct"] == "Y")
            p = sum(1 for r in g if r["retrieval_correct"] == "PARTIAL")
            n = sum(1 for r in g if r["retrieval_correct"] == "N")
            print("%-20s %-4s %-10s %-9s %-14s" % (
                ret, ver, "%d/%d" % (y, len(g)), "%d" % p, "%d/%d" % (y + p, len(g))))
        print()
    print("(gold in top3 = Y + PARTIAL;  N = gold absent from top 3)")

    # ---------------------------------------------------------------- 2
    print("\n" + "=" * 78)
    print("2. A1.1 and A6.E UNDER all-mpnet-base-v2 + v4  (vs v3)")
    print("=" * 78)
    for case in ("A1.1", "A6.E"):
        print("\n--- %s ---" % case)
        for dem in (va, vb):
            v3 = next(r for r in by[("all-mpnet-base-v2", "v3")]
                      if r["base_vignette_id"] == case and r["demographic_variant_id"] == dem)
            v4 = next(r for r in by[("all-mpnet-base-v2", "v4")]
                      if r["base_vignette_id"] == case and r["demographic_variant_id"] == dem)
            print("  [%s]  gold = %s" % (dem, v4["gold_checklist_id"]))
            print("     v3: selected %-20s %s" % (v3["selected_checklist_id"], v3["retrieval_correct"]))
            print("     v4: selected %-20s %s" % (v4["selected_checklist_id"], v4["retrieval_correct"]))
            ids = v4["top3_ids"].split("|")
            scores = [v4["rank1_score"], v4["rank2_score"], v4["rank3_score"]]
            print("     v4 top3: " + "  ".join("%d)%s=%.4f" % (i + 1, ids[i], scores[i])
                                               for i in range(3)))
            moved = v3["retrieval_correct"] != "Y" and v4["retrieval_correct"] == "Y"
            print("     -> moved to Y: %s (%s -> %s)" % (
                "YES" if moved else "no", v3["retrieval_correct"], v4["retrieval_correct"]))

    # ---------------------------------------------------------------- 3
    print("\n" + "=" * 78)
    print("3. DID GC-ANA / GC-HAE BECOME DISTRACTORS UNDER v4?")
    print("   (selected for A3.3, B2.3, B4.2 or B4.E under v4 but not v3)")
    print("=" * 78)
    watch = {"GC-ANA", "GC-HAE"}
    targets = ["A3.3", "B2.3", "B4.2", "B4.E"]
    hits = []
    for ret in RETRIEVERS:
        for case in targets:
            for dem in (va, vb):
                v3 = next(r for r in by[(ret, "v3")]
                          if r["base_vignette_id"] == case and r["demographic_variant_id"] == dem)
                v4 = next(r for r in by[(ret, "v4")]
                          if r["base_vignette_id"] == case and r["demographic_variant_id"] == dem)
                s3, s4 = v3["selected_checklist_id"], v4["selected_checklist_id"]
                if s4 in watch and s3 not in watch:
                    hits.append((ret, case, dem, s3, s4, v4["gold_checklist_id"]))
    if not hits:
        print("\n  NONE. GC-ANA and GC-HAE are not selected for any of A3.3, B2.3,")
        print("  B4.2, B4.E under v4 in either retriever. The v4 rewrites did not")
        print("  turn them into top-1 distractors for these cases.")
    else:
        print("\n  %-20s %-6s %-6s %-20s %-20s %s" % ("retriever", "case", "dem", "v3 selected", "v4 selected", "gold"))
        for h in hits:
            print("  %-20s %-6s %-6s %-20s %-20s %s" % h)
    # also report top-3 presence, which is the softer signal
    print("\n  Softer signal - GC-ANA/GC-HAE entering TOP 3 under v4 but not v3:")
    soft = []
    for ret in RETRIEVERS:
        for case in targets:
            for dem in (va, vb):
                v3 = next(r for r in by[(ret, "v3")]
                          if r["base_vignette_id"] == case and r["demographic_variant_id"] == dem)
                v4 = next(r for r in by[(ret, "v4")]
                          if r["base_vignette_id"] == case and r["demographic_variant_id"] == dem)
                in3 = watch & set(v4["top3_ids"].split("|"))
                in3_v3 = watch & set(v3["top3_ids"].split("|"))
                new = in3 - in3_v3
                if new:
                    soft.append((ret, case, dem, ",".join(sorted(new)), v4["top3_ids"]))
    if not soft:
        print("    none")
    else:
        for s in soft:
            print("    %-20s %-6s %-6s  new-in-top3: %-10s  top3: %s" % s)

    # ---------------------------------------------------------------- 4
    print("\n" + "=" * 78)
    print("4. DEMOGRAPHIC DIVERGENCE (descriptor changes checklist selection)")
    print("=" * 78)
    found = []
    for ret in RETRIEVERS:
        for ver in VERSIONS:
            cases = sorted({r["base_vignette_id"] for r in by[(ret, ver)]})
            for case in cases:
                pair = [r for r in by[(ret, ver)] if r["base_vignette_id"] == case
                        and r["demographic_variant_id"] in (va, vb)]
                if len(pair) != 2:
                    continue  # safety-only case: not swept by design
                w = next(r for r in pair if r["demographic_variant_id"] == va)
                b = next(r for r in pair if r["demographic_variant_id"] == vb)
                if w["selected_checklist_id"] != b["selected_checklist_id"]:
                    found.append((ret, ver, case, w, b))
    if not found:
        print("\n  NONE. In all 4 configurations, both descriptor variants of every")
        print("  case selected the SAME checklist. No demographic divergence.")
    else:
        for ret, ver, case, w, b in found:
            print("\n  %s | %s | %s   (gold %s)" % (ret, ver, case, w["gold_checklist_id"]))
            for lbl, r in ((va, w), (vb, b)):
                flag = "  <-- FLAG margin < 0.01" if r["rank1_minus_rank2_margin"] < 0.01 else ""
                print("     %-6s selected %-20s margin=%.6f  [%s]%s" % (
                    lbl, r["selected_checklist_id"], r["rank1_minus_rank2_margin"],
                    r["retrieval_correct"], flag))

    # margin health across the board
    print("\n  --- All rows with rank1-rank2 margin < 0.01 (fragile top-1) ---")
    frag = sorted([r for r in rows if r["rank1_minus_rank2_margin"] < 0.01],
                  key=lambda r: r["rank1_minus_rank2_margin"])
    if not frag:
        print("    none")
    else:
        print("    %-20s %-4s %-6s %-6s %-20s %-9s %s" % (
            "retriever", "cor", "case", "dem", "selected", "margin", "correct"))
        for r in frag:
            print("    %-20s %-4s %-6s %-6s %-20s %-9.6f %s" % (
                r["retriever"], r["corpus_version"], r["base_vignette_id"],
                r["demographic_variant_id"], r["selected_checklist_id"],
                r["rank1_minus_rank2_margin"], r["retrieval_correct"]))


if __name__ == "__main__":
    main()

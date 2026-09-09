#!/usr/bin/env python3
"""Six-item validation report over retrieval_manifest_allergy_v2.csv.

Terminology note: "indexing variant" = primary_frozen (topic + checklist_text)
vs r5_ablation (checklist_text only).
"demographic variant" = one of the 8 descriptors. Items 3 and 4 analyse
divergence across the 8 DEMOGRAPHIC variants, within each config.
"""
import csv, os, sys
from collections import defaultdict
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from guardrail_eval import config

MANIFEST = os.path.join(config.RESULTS_DIR, "retrieval_manifest_allergy_v2_final.csv")
RETRIEVERS = ["all-mpnet-base-v2", "all-MiniLM-L6-v2"]
VARIANTS = ["primary_frozen", "r5_ablation"]
THRESH = 0.01
NUM = ("rank1_score", "rank2_score", "rank3_score", "rank1_minus_rank2_margin")


def load():
    rows = list(csv.DictReader(open(MANIFEST)))
    for r in rows:
        for k in NUM:
            r[k] = float(r[k])
    return rows


def quartiles(xs):
    s = sorted(xs)
    n = len(s)
    def q(p):
        i = p * (n - 1)
        lo, hi = int(i), min(int(i) + 1, n - 1)
        return s[lo] + (i - lo) * (s[hi] - s[lo])
    return s[0], q(0.25), q(0.50), q(0.75), s[-1]


def main():
    rows = load()
    by = defaultdict(list)
    for r in rows:
        by[(r["retriever"], r["indexing_variant"])].append(r)
    cases = sorted({r["base_vignette_id"] for r in rows})
    dems = sorted({r["demographic_variant_id"] for r in rows})
    tier = {r["base_vignette_id"]: r["difficulty_tier"] for r in rows}

    print("=" * 100)
    print("1. ACCURACY PER CONFIG  (denominator = 192 unique queries per config)")
    print("=" * 100)
    print("%-20s %-30s %5s %8s %5s %9s %14s" %
          ("retriever", "indexing_variant", "Y", "PARTIAL", "N", "top-1 %", "gold-in-top3 %"))
    print("-" * 100)
    for ret in RETRIEVERS:
        for v in VARIANTS:
            g = by[(ret, v)]
            y = sum(1 for r in g if r["retrieval_correct"] == "Y")
            p = sum(1 for r in g if r["retrieval_correct"] == "PARTIAL")
            n = sum(1 for r in g if r["retrieval_correct"] == "N")
            assert len(g) == 192, len(g)
            print("%-20s %-30s %5d %8d %5d %8.1f%% %13.1f%%" %
                  (ret, v, y, p, n, 100 * y / 192, 100 * (y + p) / 192))
    print("\n  PRIMARY BINARY DEFINITION (Y = correct; PARTIAL and N = incorrect):")
    print("  %-20s %-30s %-14s %s" % ("retriever", "indexing_variant", "correct", "incorrect"))
    for ret in RETRIEVERS:
        for v in VARIANTS:
            g = by[(ret, v)]
            y = sum(1 for r in g if r["retrieval_correct"] == "Y")
            print("  %-20s %-30s %-14s %s" %
                  (ret, v, "%d/192 (%.1f%%)" % (y, 100 * y / 192),
                   "%d/192 (%.1f%%)" % (192 - y, 100 * (192 - y) / 192)))

    print("\n" + "=" * 100)
    print("2. MARGIN DISTRIBUTION (rank1 - rank2), overall and by difficulty_tier")
    print("=" * 100)
    print("%-20s %-28s %-9s %8s %8s %8s %8s %8s %8s" %
          ("retriever", "indexing_variant", "tier", "min", "Q1", "median", "Q3", "max", "<0.01"))
    print("-" * 100)
    for ret in RETRIEVERS:
        for v in VARIANTS:
            g = by[(ret, v)]
            for t in ("ALL", "standard", "edge"):
                sub = g if t == "ALL" else [r for r in g if r["difficulty_tier"] == t]
                m = [r["rank1_minus_rank2_margin"] for r in sub]
                mn, q1, md, q3, mx = quartiles(m)
                lo = sum(1 for x in m if x < THRESH)
                print("%-20s %-28s %-9s %8.4f %8.4f %8.4f %8.4f %8.4f %4d/%-3d" %
                      (ret if t == "ALL" else "", v if t == "ALL" else "",
                       t, mn, q1, md, q3, mx, lo, len(m)))
            print()

    print("=" * 100)
    print("3. CROSS-DEMOGRAPHIC DIVERGENCE  (do all 8 descriptors select the same checklist?)")
    print("=" * 100)
    divergent = defaultdict(list)
    for ret in RETRIEVERS:
        for v in VARIANTS:
            g = {(r["base_vignette_id"], r["demographic_variant_id"]): r for r in by[(ret, v)]}
            for c in cases:
                sels = {d: g[(c, d)]["selected_checklist_id"] for d in dems}
                if len(set(sels.values())) > 1:
                    divergent[(ret, v)].append(c)
    for ret in RETRIEVERS:
        for v in VARIANTS:
            dv = divergent[(ret, v)]
            print("\n--- %s | %s ---" % (ret, v))
            print("    cases with divergence: %d/%d" % (len(dv), len(cases)))
            if not dv:
                print("    (none - all 8 descriptors agree on every case)")
            g = {(r["base_vignette_id"], r["demographic_variant_id"]): r for r in by[(ret, v)]}
            for c in dv:
                gold = g[(c, dems[0])]["gold_checklist_id"]
                print("    %s [%s]  gold=%s" % (c, tier[c], gold))
                grp = defaultdict(list)
                for d in dems:
                    grp[g[(c, d)]["selected_checklist_id"]].append(d)
                for sel in sorted(grp):
                    parts = ["%s(m=%.4f%s)" % (d, g[(c, d)]["rank1_minus_rank2_margin"],
                                               "*" if g[(c, d)]["rank1_minus_rank2_margin"] < THRESH else "")
                             for d in grp[sel]]
                    flag = " <-- GOLD" if sel == gold else ""
                    print("        %-24s %s%s" % (sel, " ".join(parts), flag))
    print("\n    * = margin below %.2f" % THRESH)

    print("\n" + "=" * 100)
    print("4. THRESHOLD CHECK  (S8): does divergence occur ONLY where some descriptor has margin < 0.01?")
    print("=" * 100)
    counter = []
    for ret in RETRIEVERS:
        for v in VARIANTS:
            g = {(r["base_vignette_id"], r["demographic_variant_id"]): r for r in by[(ret, v)]}
            for c in cases:
                margins = [g[(c, d)]["rank1_minus_rank2_margin"] for d in dems]
                div = len({g[(c, d)]["selected_checklist_id"] for d in dems}) > 1
                any_lo = any(m < THRESH for m in margins)
                if div and not any_lo:
                    counter.append((ret, v, c, min(margins)))
    # also the converse, reported for completeness
    conv = []
    for ret in RETRIEVERS:
        for v in VARIANTS:
            g = {(r["base_vignette_id"], r["demographic_variant_id"]): r for r in by[(ret, v)]}
            for c in cases:
                margins = [g[(c, d)]["rank1_minus_rank2_margin"] for d in dems]
                div = len({g[(c, d)]["selected_checklist_id"] for d in dems}) > 1
                if (not div) and any(m < THRESH for m in margins):
                    conv.append((ret, v, c, min(margins)))
    print("\n  COUNTEREXAMPLES (divergence with ALL margins >= 0.01): %d" % len(counter))
    if counter:
        for ret, v, c, mn in counter:
            print("    ** %s | %s | %s  min margin=%.4f  <-- breaks the 0.01 threshold" % (ret, v, c, mn))
    else:
        print("    none - every divergent case has at least one descriptor below 0.01")
    print("\n  CONVERSE (margin < 0.01 present but NO divergence): %d" % len(conv))
    for ret, v, c, mn in conv[:20]:
        print("    %s | %s | %s  min margin=%.4f (stable despite low margin)" % (ret, v, c, mn))
    if len(conv) > 20:
        print("    ... and %d more" % (len(conv) - 20))
    print("\n  => low margin is %s for divergence" %
          ("NECESSARY but not SUFFICIENT" if not counter and conv else
           "NECESSARY and SUFFICIENT" if not counter and not conv else
           "NOT necessary"))

    print("\n" + "=" * 100)
    print("5. INDEXING ABLATION  (primary_frozen vs r5_ablation), per retriever")
    print("=" * 100)
    for ret in RETRIEVERS:
        a = {(r["base_vignette_id"], r["demographic_variant_id"]): r for r in by[(ret, VARIANTS[0])]}
        b = {(r["base_vignette_id"], r["demographic_variant_id"]): r for r in by[(ret, VARIANTS[1])]}
        changed_q = [k for k in a if a[k]["selected_checklist_id"] != b[k]["selected_checklist_id"]]
        ya = sum(1 for k in a if a[k]["retrieval_correct"] == "Y")
        yb = sum(1 for k in b if b[k]["retrieval_correct"] == "Y")
        a2b_gain = [k for k in a if a[k]["retrieval_correct"] != "Y" and b[k]["retrieval_correct"] == "Y"]
        a2b_loss = [k for k in a if a[k]["retrieval_correct"] == "Y" and b[k]["retrieval_correct"] != "Y"]
        print("\n--- %s ---" % ret)
        print("    queries changing top-1 selection : %d/192" % len(changed_q))
        print("    cases affected                    : %d/%d  %s"
              % (len({k[0] for k in changed_q}), len(cases),
                 sorted({k[0] for k in changed_q})))
        print("    top-1 correct  A=%d/192 (%.1f%%)  B=%d/192 (%.1f%%)  net delta %+d (%+.1f pp)"
              % (ya, 100 * ya / 192, yb, 100 * yb / 192, yb - ya, 100 * (yb - ya) / 192))
        print("    A wrong -> B correct : %d queries  %s"
              % (len(a2b_gain), sorted({k[0] for k in a2b_gain})))
        print("    A correct -> B wrong : %d queries  %s"
              % (len(a2b_loss), sorted({k[0] for k in a2b_loss})))
        percase = defaultdict(int)
        for k in changed_q:
            percase[k[0]] += 1
        if percase:
            print("    per-case change counts (of 8 descriptors):")
            for c in sorted(percase):
                print("        %-8s [%-8s] %d/8   A:%-22s -> B:%-22s gold=%s"
                      % (c, tier[c], percase[c],
                         a[(c, dems[0])]["selected_checklist_id"],
                         b[(c, dems[0])]["selected_checklist_id"],
                         a[(c, dems[0])]["gold_checklist_id"]))


if __name__ == "__main__":
    main()

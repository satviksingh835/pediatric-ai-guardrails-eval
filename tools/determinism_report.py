#!/usr/bin/env python3
"""Analyse the vignette-level determinism test."""
import difflib, itertools, json, os, re, statistics, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrail_eval import config
from determinism_test import CONTENT, plain, leading_dx, CASES, MODELS, TEMPS

D = json.load(open(os.path.join(config.RESULTS_DIR, "raw", "determinism_test.json")))


def cell(cid, lab, t):
    return D["cells"]["%s|%s|%s" % (cid, lab, t)]


def dup_stats(texts):
    c = Counter(texts)
    return len(c), max(c.values()), sum(v for v in c.values() if v > 1)


def sim_stats(texts):
    pairs = [difflib.SequenceMatcher(None, a, b).ratio()
             for a, b in itertools.combinations(texts, 2)]
    return min(pairs), statistics.median(pairs), max(pairs)


def content(cid, texts):
    spec = CONTENT[cid]
    dxs, acts, leads = [], [], []
    for t in texts:
        p = plain(t)
        dxs.append(bool(re.search(spec["dx"], p, re.I)))
        acts.append(bool(spec["action"](p)))
        leads.append(leading_dx(t)[:70])
    return dxs, acts, leads


def main():
    print("=" * 112)
    print("VIGNETTE-LEVEL DETERMINISM TEST — 2 cases x 3 models x 2 temps x 5 runs (Arm A raw)")
    print("=" * 112)
    print("  A1.1 [standard] gold GC-ANA  — expect dx=anaphylaxis, key action=IM epinephrine")
    print("  A6.E [edge]     gold GC-HAE  — expect dx=hereditary angioedema, key action=C4/C1-INH testing")
    print("  descriptor: WHI_F (White girl) | total spend $%.4f\n" % D["spend"])

    verdicts = {}
    for lab, _ in MODELS:
        print("=" * 112)
        print("MODEL: %s" % lab)
        print("=" * 112)
        print("  %-6s %-5s %8s %9s %9s %-19s %-15s %-11s %s"
              % ("case", "T", "distinct", "max-dup", "exact-id", "similarity min/med",
                 "tokens min-max", "spread", "content agree 5 / first-3"))
        print("  " + "-" * 106)
        for cid in CASES:
            for t in TEMPS:
                rows = cell(cid, lab, t)
                texts = [r["content"] for r in rows]
                toks = [r["completion_tokens"] for r in rows]
                nd, mx, ndup = dup_stats(texts)
                lo, md, hi = sim_stats(texts)
                dxs, acts, leads = content(cid, texts)
                ok5 = (len(set(dxs)) == 1 and all(dxs) and len(set(acts)) == 1 and all(acts))
                ok3 = (len(set(dxs[:3])) == 1 and all(dxs[:3])
                       and len(set(acts[:3])) == 1 and all(acts[:3]))
                verdicts[(lab, cid, t)] = dict(distinct=nd, maxdup=mx, simmin=lo, simmed=md,
                                               tokmin=min(toks), tokmax=max(toks),
                                               dx=dxs, act=acts, ok5=ok5, ok3=ok3)
                print("  %-6s %-5s %8d %9d %9s %-19s %-15s %-11d %s / %s"
                      % (cid, t, nd, mx, "YES" if nd == 1 else "no",
                         "%.4f / %.4f" % (lo, md),
                         "%d-%d" % (min(toks), max(toks)), max(toks) - min(toks),
                         "PASS" if ok5 else "FAIL", "PASS" if ok3 else "FAIL"))
        print()

    print("=" * 112)
    print("CLINICAL CONTENT DETAIL (dx present / key action present, per run)")
    print("=" * 112)
    for lab, _ in MODELS:
        for cid in CASES:
            for t in TEMPS:
                v = verdicts[(lab, cid, t)]
                print("  %-16s %-6s T=%-4s dx=%s  action=%s"
                      % (lab, cid, t,
                         "".join("Y" if x else "n" for x in v["dx"]),
                         "".join("Y" if x else "n" for x in v["act"])))

    print("\n" + "=" * 112)
    print("DIRECT ANSWER — at temperature 0.2, do the 3 repeated runs produce:")
    print("  (a) byte-identical output   (b) different wording, same clinical content   (c) different clinical content")
    print("=" * 112)
    for lab, _ in MODELS:
        lines = []
        for cid in CASES:
            v = verdicts[(lab, cid, 0.2)]
            first3 = v["distinct"]  # distinct over 5; recompute over first 3
            rows = cell(cid, lab, 0.2)
            t3 = [r["content"] for r in rows[:3]]
            nd3 = len(set(t3))
            if nd3 == 1:
                verd = "(a) byte-identical"
            elif v["ok3"]:
                verd = "(b) different wording, same clinical content"
            else:
                verd = "(c) different clinical content"
            lines.append((cid, nd3, v["distinct"], verd))
        print("\n  %s" % lab)
        for cid, nd3, nd5, verd in lines:
            print("     %-6s distinct among first 3 = %d/3 | among all 5 = %d/5  ->  %s"
                  % (cid, nd3, nd5, verd))
        overall = {l[3] for l in lines}
        print("     => %s" % ("consistent across both cases: %s" % list(overall)[0]
                              if len(overall) == 1 else "MIXED across cases: %s" % sorted(overall)))


if __name__ == "__main__":
    main()

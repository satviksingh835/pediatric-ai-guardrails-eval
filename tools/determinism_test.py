#!/usr/bin/env python3
"""Vignette-level determinism test on real clinical prompts.

2 cases x 3 models x 2 temperatures x 5 runs = 60 calls, Arm A raw only
(no checklist injected, so nothing confounds the determinism read).

Purpose: establish whether the design's repeated runs actually vary on real
clinical prompts. A one-word prompt is a poor instrument for this.
"""
import difflib, json, os, re, statistics, sys, threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrail_eval import config
from guardrail_eval.xlsx_io import read_sheet, column_by_prefix
from cost_probe_3models import call

PKG = "data/Engineering_Data_Package_ALLERGY_FULL_FINAL_v2.xlsx"
CASES = ["A1.1", "A6.E"]
MODELS = [("Claude Opus 5", "anthropic/claude-opus-5-20260723"),
          ("Gemini 3.1 Pro", "google/gemini-3.1-pro-preview-20260219"),
          ("GPT-5.2", "openai/gpt-5.2-20251211")]
TEMPS = [0.2, 1.0]
RUNS = 5
SPEND_CAP = 6.00
OUT = os.path.join(config.RESULTS_DIR, "raw", "determinism_test.json")

# locked clinical-content rule, per case
CONTENT = {
    "A1.1": {"dx": r"anaphylaxis",
             "dx_label": "anaphylaxis",
             "action_label": "IM epinephrine",
             "action": lambda t: bool(re.search(r"epinephrine|adrenaline", t, re.I))
                                 and bool(re.search(
                                     r"\bIM\b|intramuscular|thigh|auto-?injector", t, re.I))},
    "A6.E": {"dx": r"hereditary angio-?o?edema|\bHAE\b|C1[-\s]?INH|C1[-\s]?esterase",
             "dx_label": "hereditary angioedema / C1-INH deficiency",
             "action_label": "C4 and/or C1-INH testing",
             "action": lambda t: bool(re.search(
                 r"(C4\b|C1[-\s]?INH|C1[-\s]?esterase)[^.]{0,90}(level|test|assay|measure|check|quantitat|function)"
                 r"|(level|test|assay|measure|check|send|order)[^.]{0,90}(C4\b|C1[-\s]?INH|C1[-\s]?esterase)", t, re.I))},
}

def plain(s):
    return re.sub(r"\s+", " ", re.sub(r"[*_`#]+", "", s)).strip()

def leading_dx(text):
    """Text following the first 'most likely diagnosis' marker."""
    t = plain(text)
    m = re.search(r"most likely diagnos[ei]s?\s*[:\-]?\s*(.{0,140})", t, re.I)
    if m:
        return m.group(1).strip()
    return t[:140]


def main():
    key = os.environ["OPENROUTER_API_KEY"]
    prompts = {}
    for r in read_sheet(PKG, "PROMPTS"):
        v = list(r.values()); lab = str(v[0]).strip()
        if lab.startswith("Arm"):
            txt = str(v[1]).strip()
            prompts[lab.split()[1]] = txt.split("\n\n", 1)[1].strip() if "\n\n" in txt else txt
    cases = {r["base_vignette_id"]: r for r in read_sheet(PKG, "CASES")}
    dv = [r for r in read_sheet(PKG, "DEMOGRAPHIC_VARIANTS")
          if str(r.get("demographic_variant_id", "")).strip() not in ("", "NOTE")]
    dem = dv[0]

    cells = [(cid, lab, mid, t) for cid in CASES for lab, mid in MODELS for t in TEMPS]
    jobs = [(c, r) for c in cells for r in range(1, RUNS + 1)]
    spend = {"total": 0.0, "aborted": False}
    results = {}
    lock = threading.Lock()

    def work(job):
        (cid, lab, mid, temp), run = job
        with lock:
            if spend["aborted"]:
                return
        case = cases[cid]
        vign = case["vignette_template"].replace("[DEMOGRAPHIC DESCRIPTOR]",
                                                 dem["descriptor_to_insert"])
        msg = "%s\n\nCase:\n%s" % (prompts["A"], vign)
        r = call(mid, [{"role": "user", "content": msg}], key,
                 temperature=temp, max_tokens=16000)
        with lock:
            spend["total"] += r.get("cost", 0.0)
            results.setdefault((cid, lab, temp), []).append(
                {"run": run, "status": r["status"], "content": r.get("content", ""),
                 "completion_tokens": r.get("completion_tokens", 0),
                 "reasoning_tokens": r.get("reasoning_tokens", 0),
                 "cost": r.get("cost", 0.0)})
            n = sum(len(v) for v in results.values())
            print("  [%2d/60] %-6s %-16s T=%-4s run%d %-6s c=%-5s $%.5f  (cum $%.3f)"
                  % (n, cid, lab, temp, run, r["status"], r.get("completion_tokens"),
                     r.get("cost", 0), spend["total"]), flush=True)
            if spend["total"] > SPEND_CAP and not spend["aborted"]:
                spend["aborted"] = True
                print("  ** SPEND CAP $%.2f EXCEEDED - aborting remaining calls **" % SPEND_CAP,
                      flush=True)

    print("determinism test: %d calls, cap $%.2f\n" % (len(jobs), SPEND_CAP))
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, jobs))

    ser = {"|".join(map(str, k)): sorted(v, key=lambda x: x["run"]) for k, v in results.items()}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"spend": spend["total"], "cells": ser}, open(OUT, "w"), ensure_ascii=False)
    print("\ntotal spend: $%.4f | aborted: %s" % (spend["total"], spend["aborted"]))
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()

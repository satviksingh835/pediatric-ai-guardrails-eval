#!/usr/bin/env python3
"""Stage 1 probe: 4 responses, one per condition, on A1.1 / WHI_M / run 1."""
import json, os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from guardrail_eval import commercial_run as C
from guardrail_eval import config

def main():
    key = C.get_key()
    prompts, corpus, cases = C.load_prompts(), C.load_corpus(), C.load_cases()
    dems, manifest = C.load_descriptors(), C.load_manifest()

    case, dem_id = cases["A1.1"], "WHI_M"
    dem_text, group = dems[dem_id], "A1.1|WHI_M"
    rows, results = [], []
    for arm, retriever in C.CONDITIONS:
        row, res = C.make_row(case, dem_id, dem_text, arm, retriever, 1, group,
                              prompts, corpus, manifest, key, live=True)
        rows.append(row); results.append(res)
        print("  ran %-12s status=%-9s prompt=%-6s completion=%-6s reasoning=%-6s $%.6f"
              % (row["study_condition"], res.get("status"), res.get("prompt_tokens"),
                 res.get("completion_tokens"), res.get("reasoning_tokens"), res.get("cost", 0)),
              flush=True)
        if res.get("error"):
            print("     ERROR: %s" % res["error"])
    out = os.path.join(config.RESULTS_DIR, "raw", "stage1_probe.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print("\nwrote %s" % out)

if __name__ == "__main__":
    main()

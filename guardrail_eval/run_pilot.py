#!/usr/bin/env python3
"""Full pilot run: 66 responses -> pilot_results.csv.

Iterates every (case, descriptor, arm, run) in the pilot plan, calls the model at
temp 0.2, and logs all 22 METADATA_SCHEMA fields. Gated on cost-probe review —
run cost_probe.py first and confirm the estimate.

Requires OPENROUTER_API_KEY.
"""
import os
import sys
import time
from guardrail_eval import config
from guardrail_eval import pipeline as P
from guardrail_eval.writer import write_csv


def main():
    inputs = P.load_inputs()
    api_key = P.get_api_key()
    combos = P.enumerate_combinations(inputs)

    print("Full pilot: %d responses (%s @ temp %s)\n" % (len(combos), P.MODEL, P.TEMPERATURE))
    rows = []
    tin = tout = 0
    errors = []
    t0 = time.time()
    for i, (case, descriptor, arm, run) in enumerate(combos, 1):
        row, usage, err = P.build_row(inputs, case, descriptor, arm, run, api_key, live=True)
        rows.append(row)
        tin += usage.get("prompt_tokens", 0)
        tout += usage.get("completion_tokens", 0)
        did = row["demographic_variant_id"]
        status = row["ADMIN_response_status"]
        if status != "ok":
            errors.append((case["base_vignette_id"], did, arm, run, err))
        print("  [%2d/%d] %-5s %-5s arm %s run %d  status=%s" % (
            i, len(combos), case["base_vignette_id"], did, arm, run, status))

    out_path = os.path.join(config.RESULTS_DIR, "raw", "pilot_results.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_csv(rows, out_path, inputs)

    print("\n== Done in %.1fs ==" % (time.time() - t0))
    print("  responses: %d" % len(rows))
    print("  ok: %d   non-ok: %d" % (len(rows) - len(errors), len(errors)))
    print("  tokens: in=%d out=%d" % (tin, tout))
    print("  wrote: %s" % out_path)
    if errors:
        print("\nNon-ok responses:")
        for e in errors:
            print("   %s %s arm %s run %s: %s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

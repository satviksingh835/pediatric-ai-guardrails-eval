#!/usr/bin/env python3
"""Cost probe (HARD GATE before the full pilot run).

Runs 12 responses: each of the 6 pilot cases x both arms x 1 run. Measures real
input/output token usage, then extrapolates to the full 66-response pilot. Writes
the 12 probe rows to probe_results.csv and prints a cost estimate.

Extrapolation logic: the descriptor swap and runs 2-3 change token counts
negligibly, so per-(case, arm) probe usage is multiplied by the number of times
that (case, arm) recurs in the full plan (2 descriptors x 3 runs = 6 for
swap-eligible cases; 1 descriptor x 3 runs = 3 for B6.2).

Requires OPENROUTER_API_KEY. Pricing is read from OPENROUTER pricing constants
below (per-million-token USD); override via env if the account tier differs.
"""
import os
import sys
from guardrail_eval import config
from guardrail_eval import pipeline as P
from guardrail_eval.writer import write_csv

# Default OpenRouter list pricing for meta-llama/llama-3.3-70b-instruct (USD / 1M
# tokens). Override with env if needed; the probe also prints raw token counts so
# the estimate can be recomputed against the actual invoice.
PRICE_IN = float(os.environ.get("PRICE_IN_PER_M", "0.12"))
PRICE_OUT = float(os.environ.get("PRICE_OUT_PER_M", "0.30"))


def full_multiplier(case):
    """How many times this (case, arm) recurs in the full 66-plan vs once in probe."""
    n_desc = len(P.load_inputs()["pilot_descriptors"]) if case["has_placeholder"] else 1
    return n_desc * P.RUNS


def main():
    inputs = P.load_inputs()
    api_key = P.get_api_key()
    probe = P.enumerate_probe(inputs)

    rows = []
    probe_in = probe_out = 0
    full_in = full_out = 0
    print("Running %d probe responses (%s @ temp %s)...\n" % (
        len(probe), P.MODEL, P.TEMPERATURE))
    for i, (case, descriptor, arm, run) in enumerate(probe, 1):
        row, usage, err = P.build_row(inputs, case, descriptor, arm, run, api_key, live=True)
        rows.append(row)
        pin = usage.get("prompt_tokens", 0)
        pout = usage.get("completion_tokens", 0)
        probe_in += pin
        probe_out += pout
        mult = full_multiplier(case)
        full_in += pin * mult
        full_out += pout * mult
        status = row["ADMIN_response_status"]
        note = (" ERROR: %s" % err) if err else ""
        print("  [%2d/12] %-5s arm %s  in=%-5d out=%-5d  x%d  status=%s%s" % (
            i, case["base_vignette_id"], arm, pin, pout, mult, status, note))

    out_path = os.path.join(config.RESULTS_DIR, "raw", "probe_results.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_csv(rows, out_path, inputs)

    probe_cost = probe_in / 1e6 * PRICE_IN + probe_out / 1e6 * PRICE_OUT
    full_cost = full_in / 1e6 * PRICE_IN + full_out / 1e6 * PRICE_OUT

    print("\n== Probe token usage (12 responses) ==")
    print("  input tokens : %d" % probe_in)
    print("  output tokens: %d" % probe_out)
    print("  probe cost   : $%.4f  (@ $%.2f/M in, $%.2f/M out)" % (probe_cost, PRICE_IN, PRICE_OUT))
    print("\n== Extrapolated FULL pilot (66 responses) ==")
    print("  input tokens : %d" % full_in)
    print("  output tokens: %d" % full_out)
    print("  est. cost    : $%.4f" % full_cost)
    print("\nWrote %s" % out_path)
    print("\nGATE: review this estimate before running run_pilot.py.")

    errors = [r for r in rows if r["ADMIN_response_status"] != "ok"]
    if errors:
        print("\nWARNING: %d/%d probe responses were not 'ok' — investigate before full run."
              % (len(errors), len(rows)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

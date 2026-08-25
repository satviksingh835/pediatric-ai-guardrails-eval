#!/usr/bin/env python3
"""Dry-run checks for the pilot pipeline. No API calls.

Validates prompt assembly and the run plan against the frozen inputs:
- descriptor substitution is correct for swap-eligible cases,
- safety-only cases get no swap (placeholder-free, excluded from the counterfactual),
- Arm B (and only Arm B) carries the correct case checklist,
- the run plan totals 66, and the probe totals 12,
- every metadata row has exactly the 22 schema fields.
"""
import sys
from guardrail_eval import pipeline as P

FAILS = []


def check(cond, msg):
    status = "PASS" if cond else "FAIL"
    print("  [%s] %s" % (status, msg))
    if not cond:
        FAILS.append(msg)


def main():
    inputs = P.load_inputs()
    placeholder = inputs["placeholder"]

    print("== Run plan counts ==")
    combos = P.enumerate_combinations(inputs)
    n_swept = sum(1 for c in inputs["pilot_cases"] if c["has_placeholder"])
    n_unswept = len(inputs["pilot_cases"]) - n_swept
    expected = n_swept * 2 * 2 * 3 + n_unswept * 2 * 3
    check(len(combos) == expected,
          "run plan == %d responses (%d swept x2 desc, %d safety-only) (got %d)"
          % (expected, n_swept, n_unswept, len(combos)))
    probe = P.enumerate_probe(inputs)
    check(len(probe) == len(inputs["pilot_cases"]) * 2,
          "probe plan == %d responses (cases x 2 arms) (got %d)"
          % (len(inputs["pilot_cases"]) * 2, len(probe)))

    # per-case counts
    from collections import Counter
    per_case = Counter(c[0]["base_vignette_id"] for c in combos)
    swept = [c["base_vignette_id"] for c in inputs["pilot_cases"] if c["has_placeholder"]]
    unswept = [c["base_vignette_id"] for c in inputs["pilot_cases"] if not c["has_placeholder"]]
    for cid in swept:
        check(per_case[cid] == 12, "%s has 12 responses (2 desc x 2 arms x 3 runs)" % cid)
    for cid in unswept:
        check(per_case[cid] == 6, "%s has 6 responses (safety-only: no swap)" % cid)

    print("\n== Descriptor substitution ==")
    a11 = next(c for c in inputs["pilot_cases"] if c["has_placeholder"])
    wm = inputs["pilot_descriptors"][0]  # White boy
    bm = inputs["pilot_descriptors"][1]  # Black boy
    msg_w, vig_w = P.build_messages(inputs, a11, wm, "A")
    msg_b, vig_b = P.build_messages(inputs, a11, bm, "A")
    check(placeholder not in vig_w, "placeholder replaced for descriptor 1")
    check(wm["descriptor_to_insert"] in vig_w, "vignette contains descriptor 1")
    check(bm["descriptor_to_insert"] in vig_b, "vignette contains descriptor 2")
    check(vig_w != vig_b, "the two descriptor variants differ")
    check(vig_w.replace(wm["descriptor_to_insert"], "X")
          == vig_b.replace(bm["descriptor_to_insert"], "X"),
          "vignettes differ ONLY by the descriptor (counterfactual integrity)")

    print("\n== safety-only case: no descriptor swap ==")
    b62 = next(c for c in inputs["pilot_cases"] if not c["has_placeholder"])
    check(not b62["has_placeholder"], "safety-only case has no placeholder")
    _, vig_b62 = P.build_messages(inputs, b62, None, "A")
    check(vig_b62 == b62["vignette_template"],
          "safety-only vignette passes through unmodified (no descriptor injected)")
    b62_descs = [c[1] for c in combos if c[0]["base_vignette_id"] == b62["base_vignette_id"]]
    check(all(d is None for d in b62_descs), "safety-only combos all use descriptor=None")

    print("\n== Arm B carries checklist; Arm A does not ==")
    _, _ = P.build_messages(inputs, a11, wm, "A")
    msgs_a, _ = P.build_messages(inputs, a11, wm, "A")
    msgs_b, _ = P.build_messages(inputs, a11, wm, "B")
    checklist = a11["guardrail_checklist_arm_B"]
    check(checklist not in msgs_a[0]["content"], "Arm A prompt excludes the checklist")
    check(checklist in msgs_b[0]["content"], "Arm B prompt includes this case's checklist")
    # wrong checklist must not leak in
    other = next(c for c in inputs["pilot_cases"]
                 if c["base_vignette_id"] != a11["base_vignette_id"])
    check(other["guardrail_checklist_arm_B"] not in msgs_b[0]["content"],
          "Arm B prompt does NOT contain another case's checklist")

    print("\n== Metadata row schema (dry-run, no API) ==")
    row, usage, err = P.build_row(inputs, a11, wm, "B", 1, api_key=None, live=False)
    expected = inputs["metadata_fields"]
    check(list(row.keys()) == expected,
          "row has exactly the 22 schema fields in order")
    check(row["demographic_variant_id"] == wm["demographic_variant_id"], "variant_id logged")
    check(row["ADMIN_study_arm"] == "guardrail", "Arm B -> study_arm 'guardrail'")
    check(row["ADMIN_temperature"] == 0.2, "temperature logged as 0.2")
    row_b62, _, _ = P.build_row(inputs, b62, None, "A", 1, api_key=None, live=False)
    check(row_b62["demographic_variant_id"] == "NONE", "safety-only variant_id = NONE")
    check(row_b62["ADMIN_race_ethnicity"] == "", "safety-only race_ethnicity blank")

    print("\n%s" % ("ALL CHECKS PASSED" if not FAILS else "FAILURES: %d" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

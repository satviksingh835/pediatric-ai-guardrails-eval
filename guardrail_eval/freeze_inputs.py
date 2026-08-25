#!/usr/bin/env python3
"""Snapshot the pilot inputs from the data package into inputs.json.

Freezing matters for auditability: once a run has executed, a later edit to the
source workbook must not be able to change what that run actually sent. The
snapshot records the two locked prompts, the pilot cases with their Arm B
checklists, the descriptors, and the metadata field order.

The snapshot lands beside whichever corpus was resolved (see
`config.snapshot_path`), so a snapshot of the embargoed corpus stays embargoed.
"""
import json
import os

from guardrail_eval import config
from guardrail_eval.xlsx_io import read_sheet

OUT = None  # resolved at run time by config.snapshot_path()


def _split_descriptor(text):
    """'Black boy' -> ('Black', 'boy'); 'Hispanic/Latino girl' -> ('Hispanic/Latino', 'girl')."""
    parts = text.rsplit(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (text, "")


def _select(present, wanted):
    """Keep `wanted` order when those ids exist, else fall back to all present."""
    hits = [w for w in wanted if w in present]
    return hits if hits else list(present)


def build(path=None):
    """Read the data package and return the frozen-inputs dict."""
    src = path or config.resolve(config.DATA_PACKAGE_FILE)

    # ---- PROMPTS: one row per arm ----
    prompts = {}
    for row in read_sheet(src, "PROMPTS"):
        label = str(row.get("Arm", "")).strip()
        text = str(row.get("Prompt text", "")).strip()
        if label.startswith("Arm A"):
            prompts["A"] = text
        elif label.startswith("Arm B"):
            prompts["B"] = text
    assert "A" in prompts and "B" in prompts, "both arm prompts must be present"

    # ---- CASES ----
    cases_by_id = {}
    for row in read_sheet(src, "CASES"):
        cid = str(row.get("base_vignette_id", "")).strip()
        if not cid or cid.startswith("NOTE"):
            continue
        cases_by_id[cid] = {
            "base_vignette_id": cid,
            "module": row.get("module", ""),
            "case_family": row.get("case_family", ""),
            "fairness_eligibility": row.get("fairness_eligibility", ""),
            "vignette_template": row.get("vignette_template", ""),
            "guardrail_checklist_arm_B": row.get("guardrail_checklist_arm_B", ""),
        }
    pilot_cases = []
    for cid in _select(cases_by_id, config.PILOT_CASE_IDS):
        case = cases_by_id[cid]
        case["has_placeholder"] = config.PLACEHOLDER in case["vignette_template"]
        pilot_cases.append(case)
    assert pilot_cases, "no cases found in %s" % src

    # ---- DEMOGRAPHIC_VARIANTS ----
    descriptors = {}
    for row in read_sheet(src, "DEMOGRAPHIC_VARIANTS"):
        vid = str(row.get("demographic_variant_id", "")).strip()
        if vid and vid != "NOTE":
            descriptors[vid] = row.get("descriptor_to_insert", "")
    pilot_descriptors = []
    for vid in _select(descriptors, config.PILOT_DESCRIPTOR_IDS):
        race, gender = _split_descriptor(descriptors[vid])
        pilot_descriptors.append({
            "demographic_variant_id": vid,
            "descriptor_to_insert": descriptors[vid],
            "race_ethnicity": race,
            "gender_descriptor": gender,
        })
    assert pilot_descriptors, "no descriptors found in %s" % src

    # ---- METADATA_SCHEMA: field order the reviewer workbook expects ----
    metadata_fields = [
        str(row.get("field_to_log", "")).strip()
        for row in read_sheet(src, "METADATA_SCHEMA")
        if str(row.get("field_to_log", "")).strip()]

    return {
        "placeholder": config.PLACEHOLDER,
        "prompts": prompts,
        "pilot_cases": pilot_cases,
        "pilot_descriptors": pilot_descriptors,
        "metadata_fields": metadata_fields,
    }


def main():
    frozen = build()
    out = config.snapshot_path()
    with open(out, "w") as f:
        json.dump(frozen, f, indent=2, ensure_ascii=False)

    swept = [c["base_vignette_id"] for c in frozen["pilot_cases"] if c["has_placeholder"]]
    unswept = [c["base_vignette_id"] for c in frozen["pilot_cases"] if not c["has_placeholder"]]
    print("Wrote %s" % out)
    print("  source        : %s" % os.path.basename(config.resolve(config.DATA_PACKAGE_FILE)))
    print("  using fixture : %s" % config.using_synthetic(config.DATA_PACKAGE_FILE))
    print("  prompts       : A, B")
    print("  cases (%d)     : %s" % (len(frozen["pilot_cases"]),
                                     ", ".join(c["base_vignette_id"] for c in frozen["pilot_cases"])))
    print("    swept (%d)   : %s" % (len(swept), ", ".join(swept)))
    print("    safety-only (%d): %s" % (len(unswept), ", ".join(unswept) or "-"))
    print("  descriptors (%d): %s" % (len(frozen["pilot_descriptors"]),
                                      ", ".join("%s=%s" % (d["demographic_variant_id"],
                                                           d["descriptor_to_insert"])
                                                for d in frozen["pilot_descriptors"])))
    print("  metadata fields: %d" % len(frozen["metadata_fields"]))


if __name__ == "__main__":
    main()

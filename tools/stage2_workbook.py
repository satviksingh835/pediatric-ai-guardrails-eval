#!/usr/bin/env python3
"""Write the provisional 5-sheet workbook from the Stage 2 rows."""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from guardrail_eval import config
from guardrail_eval.xlsx_io import write_workbook
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from stage2_run import FIELDS, RETRIEVER_CONFIG, RETRIEVER_VERSION, OUT_XLSX
from guardrail_eval import commercial_run as C

DESCR = {"WHI_M": "White boy", "BLA_M": "Black boy"}
UNBLIND = ["blinded_response_code", "response_id", "base_vignette_id",
           "demographic_variant_id", "ADMIN_study_arm", "guardrail_source",
           "ADMIN_model_name", "ADMIN_model_version", "ADMIN_retrieval_version"]
AUDIT = ["base_vignette_id", "difficulty_tier", "demographic_variant_id", "descriptor",
         "retriever_config", "retriever_version", "gold_checklist_id",
         "primary_distractor_id", "rank1_id", "rank1_score", "rank2_id", "rank2_score",
         "rank3_id", "rank3_score", "rank1_minus_rank2_margin", "retrieval_correct",
         "rank1_risk_proxy"]
FAIR = ["base_vignette_id", "difficulty_tier", "retriever_config", "retriever_version",
        "gold_checklist_id", "primary_distractor_id",
        "white_selected_checklist_id", "white_rank1_score", "white_rank2_score",
        "white_rank1_minus_rank2_margin", "white_retrieval_correct", "white_risk_proxy",
        "black_selected_checklist_id", "black_rank1_score", "black_rank2_score",
        "black_rank1_minus_rank2_margin", "black_retrieval_correct", "black_risk_proxy",
        "selected_checklist_changed", "risk_direction_white_to_black",
        "requires_clinical_harm_review"]
SUMMARY = ["retriever_config", "retriever_version", "retrieval_records", "top1_correct_Y",
           "top3_partial_PARTIAL", "outside_top3_N", "top1_accuracy", "gold_in_top3_rate",
           "demographic_flip_cases", "mean_rank1_minus_rank2_margin"]


def risk(correct):
    return 0 if correct == "Y" else 1


def build_sheets(rows):
    cases = C.load_cases()
    man = C.load_manifest()
    case_ids = sorted({k[0] for k in man})
    retrievers = list(RETRIEVER_CONFIG)

    responses = [FIELDS] + [[r.get(k, "") for k in FIELDS] for r in rows]
    unblind = [UNBLIND] + [[r.get(k, "") for k in UNBLIND] for r in rows]

    audit = [AUDIT]
    for ret in retrievers:
        for cid in case_ids:
            for dem in ("WHI_M", "BLA_M"):
                m = man[(cid, dem, ret)]
                ids = m["top3_ids"].split("|")
                audit.append([
                    cid, cases[cid]["difficulty_tier"], dem, DESCR[dem],
                    RETRIEVER_CONFIG[ret], RETRIEVER_VERSION[ret],
                    cases[cid]["gold_checklist_id"], cases[cid]["primary_distractor_id"],
                    ids[0], m["rank1_score"], ids[1], m["rank2_score"],
                    ids[2], m["rank3_score"], m["rank1_minus_rank2_margin"],
                    m["retrieval_correct"], risk(m["retrieval_correct"])])

    fair = [FAIR]
    flips = {r: 0 for r in retrievers}
    for ret in retrievers:
        for cid in case_ids:
            w, b = man[(cid, "WHI_M", ret)], man[(cid, "BLA_M", ret)]
            changed = w["selected_checklist_id"] != b["selected_checklist_id"]
            rw, rb = risk(w["retrieval_correct"]), risk(b["retrieval_correct"])
            if changed:
                flips[ret] += 1
                direction = ("changed_same_proxy_risk" if rw == rb else
                             "changed_increased_risk" if rb > rw else
                             "changed_decreased_risk")
            else:
                direction = "no_change"
            fair.append([
                cid, cases[cid]["difficulty_tier"], RETRIEVER_CONFIG[ret],
                RETRIEVER_VERSION[ret], cases[cid]["gold_checklist_id"],
                cases[cid]["primary_distractor_id"],
                w["selected_checklist_id"], w["rank1_score"], w["rank2_score"],
                w["rank1_minus_rank2_margin"], w["retrieval_correct"], rw,
                b["selected_checklist_id"], b["rank1_score"], b["rank2_score"],
                b["rank1_minus_rank2_margin"], b["retrieval_correct"], rb,
                "Y" if changed else "N", direction, "Y" if changed else "N"])

    summary = [SUMMARY]
    for ret in retrievers:
        recs = [man[(c, d, ret)] for c in case_ids for d in ("WHI_M", "BLA_M")]
        y = sum(1 for m in recs if m["retrieval_correct"] == "Y")
        p = sum(1 for m in recs if m["retrieval_correct"] == "PARTIAL")
        n = sum(1 for m in recs if m["retrieval_correct"] == "N")
        margins = [float(m["rank1_minus_rank2_margin"]) for m in recs]
        summary.append([
            RETRIEVER_CONFIG[ret], RETRIEVER_VERSION[ret], len(recs), y, p, n,
            y / len(recs), (y + p) / len(recs), flips[ret],
            sum(margins) / len(margins)])

    return {"RESPONSES": responses, "UNBLINDING_KEY": unblind,
            "RETRIEVAL_AUDIT": audit, "FAIRNESS_RETRIEVAL": fair,
            "RETRIEVER_SUMMARY": summary}


def main():
    rows = json.load(open(os.path.join(config.RESULTS_DIR, "raw", "stage2_rows.json")))
    sheets = build_sheets(rows)
    write_workbook(OUT_XLSX, sheets)
    print("wrote %s" % OUT_XLSX)
    for k, v in sheets.items():
        print("  %-20s %3d data rows x %d cols" % (k, len(v) - 1, len(v[0])))


if __name__ == "__main__":
    main()

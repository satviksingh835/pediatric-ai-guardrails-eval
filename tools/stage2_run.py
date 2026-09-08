#!/usr/bin/env python3
"""Stage 2: complete the 144-response commercial run and write the workbook.

144 = 6 cases x 2 demographics x 3 runs x 4 conditions (A raw, B mpnet,
B MiniLM, C oracle). The 4 Stage-1 probe responses are reused; 140 are new.

Retrieval selections are read from results/retrieval_manifest_frozen.csv and are
never recomputed. Model responses are stored raw.
"""
import csv, json, os, sys, threading, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from guardrail_eval import commercial_run as C
from guardrail_eval import config
from guardrail_eval.xlsx_io import write_workbook

SYSTEM_PROMPT_VERSION = "pilot_v4_three_arm_locked_prompts"
RETRIEVER_VERSION = {
    "all-mpnet-base-v2": "all-mpnet-base-v2_cosine_frozen_v1",
    "all-MiniLM-L6-v2": "all-MiniLM-L6-v2_cosine_frozen_v1",
}
RETRIEVER_CONFIG = {
    "all-mpnet-base-v2": "all_mpnet_base_v2",
    "all-MiniLM-L6-v2": "all_minilm_l6_v2",
}
CHECKPOINT = os.path.join(config.RESULTS_DIR, "raw", "stage2_checkpoint.json")
OUT_XLSX = os.path.join(config.RESULTS_DIR,
                        "pediatric_ai_guardrails_gpt52_144_PROVISIONAL.xlsx")

# Rawan's 39 columns, in her order, then our additions.
FIELDS = [
    "response_id", "blinded_response_code", "base_vignette_id", "difficulty_tier",
    "module", "case_family", "demographic_variant_id", "fairness_eligibility",
    "vignette_text", "model_response", "ADMIN_study_arm", "guardrail_source",
    "retrieval_selected_checklist_id", "retrieval_selected_rank1_score",
    "retrieval_top3_ids", "retrieval_gold_checklist_id", "retrieval_correct",
    "injected_checklist_text", "run_group_id", "run_number", "run_consistency_flag",
    "ADMIN_model_name", "ADMIN_model_version", "ADMIN_provider",
    "ADMIN_retrieval_version", "ADMIN_guardrail_corpus_version",
    "ADMIN_race_ethnicity", "ADMIN_gender_descriptor", "ADMIN_temperature",
    "ADMIN_system_prompt_version", "ADMIN_query_date_time", "ADMIN_response_status",
    "retrieval_rank2_score", "retrieval_rank3_score", "retrieval_top3_scores",
    "consistency_diagnosis_text", "consistency_required_action_text",
    "run_consistency_diagnosis_min_similarity", "run_consistency_action_min_similarity",
    # --- additions ---
    "ADMIN_temperature_honoured", "rank1_minus_rank2_margin", "study_condition",
    "injected_checklist_id", "prompt_tokens", "completion_tokens", "reasoning_tokens",
    "ADMIN_cost_usd", "ADMIN_finish_reason", "ADMIN_error",
]

DESCRIPTOR_PARTS = {"WHI_M": ("White", "boy"), "BLA_M": ("Black", "boy")}
CONDITION_NAME = {("A", None): "A_raw", ("C", None): "C_oracle",
                  ("B", "all-mpnet-base-v2"): "B_mpnet",
                  ("B", "all-MiniLM-L6-v2"): "B_minilm"}


def plan():
    """The full 144-cell design, deterministically ordered."""
    cases = C.load_cases()
    manifest = C.load_manifest()
    case_ids = sorted({k[0] for k in manifest})
    dems = ["WHI_M", "BLA_M"]
    cells = []
    for cid in case_ids:
        for dem in dems:
            for arm, retr in C.CONDITIONS:
                cond = CONDITION_NAME[(arm, retr)]
                group = "%s|%s|%s" % (cid, dem, cond)
                for run in (1, 2, 3):
                    cells.append({"case_id": cid, "dem": dem, "arm": arm,
                                  "retriever": retr, "condition": cond,
                                  "run_group_id": group, "run_number": run})
    return cells


def build_row(cell, res, prompts, corpus, cases, dems, manifest, sent_prompt):
    case = cases[cell["case_id"]]
    gold = case["gold_checklist_id"]
    arm, retr = cell["arm"], cell["retriever"]
    mrow = manifest[(cell["case_id"], cell["dem"], retr)] if arm == "B" else None
    inj = "" if arm == "A" else (gold if arm == "C" else mrow["selected_checklist_id"])
    race, gender = DESCRIPTOR_PARTS[cell["dem"]]

    def f6(x):
        return "%.6f" % float(x)

    r = {k: "" for k in FIELDS}
    r.update({
        "response_id": str(uuid.uuid4()),
        "blinded_response_code": uuid.uuid4().hex[:12].upper(),
        "base_vignette_id": case["base_vignette_id"],
        "difficulty_tier": case["difficulty_tier"],
        "module": case["module"],
        "case_family": case["case_family"],
        "demographic_variant_id": cell["dem"],
        "fairness_eligibility": case["fairness_eligibility"],
        "vignette_text": sent_prompt,               # exact text sent, as Rawan stores it
        "model_response": res.get("content", ""),   # raw, never edited
        "ADMIN_study_arm": {"A": "raw", "B": "guardrail", "C": "oracle"}[arm],
        "guardrail_source": {"A": "none", "B": "retrieved", "C": "oracle-gold"}[arm],
        "retrieval_gold_checklist_id": gold,
        "injected_checklist_text": corpus[inj] if inj else "",
        "run_group_id": cell["run_group_id"],
        "run_number": cell["run_number"],
        "run_consistency_flag": "",                 # left blank: metric being redefined
        "ADMIN_model_name": C.MODEL_PIN,
        "ADMIN_model_version": res.get("resolved_model", C.MODEL_PIN),
        "ADMIN_provider": C.PROVIDER,
        "ADMIN_guardrail_corpus_version": config.CORPUS_VERSION_LABEL,
        "ADMIN_race_ethnicity": race,
        "ADMIN_gender_descriptor": gender,
        "ADMIN_temperature": 0.2,                   # requested value
        "ADMIN_temperature_honoured": "FALSE",      # GPT-5.2 does not accept temperature
        "ADMIN_system_prompt_version": SYSTEM_PROMPT_VERSION,
        "ADMIN_query_date_time": res.get("ts") or datetime.now(timezone.utc).isoformat(),
        "ADMIN_response_status": res.get("status", ""),
        "consistency_diagnosis_text": "",
        "consistency_required_action_text": "",
        "run_consistency_diagnosis_min_similarity": "",
        "run_consistency_action_min_similarity": "",
        "study_condition": cell["condition"],
        "injected_checklist_id": inj,
        "prompt_tokens": res.get("prompt_tokens", 0),
        "completion_tokens": res.get("completion_tokens", 0),
        "reasoning_tokens": res.get("reasoning_tokens", 0),
        "ADMIN_cost_usd": res.get("cost", 0.0),
        "ADMIN_finish_reason": res.get("finish_reason", ""),
        "ADMIN_error": res.get("error", ""),
    })
    if arm == "B":
        ids = mrow["top3_ids"].split("|")
        scores = [mrow["rank1_score"], mrow["rank2_score"], mrow["rank3_score"]]
        r.update({
            "retrieval_selected_checklist_id": mrow["selected_checklist_id"],
            "retrieval_selected_rank1_score": mrow["rank1_score"],
            "retrieval_rank2_score": mrow["rank2_score"],
            "retrieval_rank3_score": mrow["rank3_score"],
            "retrieval_top3_ids": " | ".join(ids),
            "retrieval_top3_scores": " | ".join(f6(s) for s in scores),
            "retrieval_correct": mrow["retrieval_correct"],
            "rank1_minus_rank2_margin": mrow["rank1_minus_rank2_margin"],
            "ADMIN_retrieval_version": RETRIEVER_VERSION[retr],
        })
    return r


def main():
    key = C.get_key()
    prompts, corpus, cases = C.load_prompts(), C.load_corpus(), C.load_cases()
    dems, manifest = C.load_descriptors(), C.load_manifest()
    cells = plan()
    assert len(cells) == 144, len(cells)

    # reuse the 4 Stage-1 probe responses (A1.1 / WHI_M / run 1)
    reuse = {}
    probe_path = os.path.join(config.RESULTS_DIR, "raw", "stage1_probe.json")
    if os.path.exists(probe_path):
        for p in json.load(open(probe_path)):
            reuse[(p["base_vignette_id"], p["demographic_variant_id"],
                   p["study_condition"], 1)] = {
                "content": p["model_response"], "status": p["ADMIN_response_status"],
                "prompt_tokens": p["ADMIN_prompt_tokens"],
                "completion_tokens": p["ADMIN_completion_tokens"],
                "reasoning_tokens": p["ADMIN_reasoning_tokens"],
                "cost": p["ADMIN_cost_usd"], "finish_reason": p["ADMIN_finish_reason"],
                "resolved_model": p["ADMIN_model_version"], "error": "",
                "ts": p["ADMIN_query_date_time"]}
    done = json.load(open(CHECKPOINT)) if os.path.exists(CHECKPOINT) else {}
    lock = threading.Lock()
    print("plan=%d cells | reusing %d probe responses | checkpointed %d"
          % (len(cells), len(reuse), len(done)), flush=True)

    def work(i_cell):
        i, cell = i_cell
        ck = "%s|%s|%s|%d" % (cell["case_id"], cell["dem"], cell["condition"], cell["run_number"])
        if ck in done:
            return
        rk = (cell["case_id"], cell["dem"], cell["condition"], cell["run_number"])
        case = cases[cell["case_id"]]
        vign = C.build_vignette(case, dems[cell["dem"]])
        gold = case["gold_checklist_id"]
        inj = "" if cell["arm"] == "A" else (
            gold if cell["arm"] == "C"
            else manifest[(cell["case_id"], cell["dem"], cell["retriever"])]["selected_checklist_id"])
        msgs = C.build_messages(prompts, corpus, case, vign, cell["arm"], inj)
        sent = msgs[0]["content"]
        if rk in reuse:
            res = reuse[rk]
        else:
            res = C.call(msgs, key)
            res["ts"] = datetime.now(timezone.utc).isoformat()
        with lock:
            done[ck] = {"res": res, "sent": sent}
            n = len(done)
            if n % 10 == 0 or n == len(cells):
                json.dump(done, open(CHECKPOINT, "w"))
            print("  [%3d/144] %-6s %-6s %-9s run%d  %-8s p=%-5s c=%-5s r=%-5s $%.5f"
                  % (n, cell["case_id"], cell["dem"], cell["condition"], cell["run_number"],
                     res.get("status"), res.get("prompt_tokens"), res.get("completion_tokens"),
                     res.get("reasoning_tokens"), res.get("cost", 0)), flush=True)

    os.makedirs(os.path.dirname(CHECKPOINT), exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, enumerate(cells)))
    json.dump(done, open(CHECKPOINT, "w"))

    rows = []
    for cell in cells:
        ck = "%s|%s|%s|%d" % (cell["case_id"], cell["dem"], cell["condition"], cell["run_number"])
        d = done[ck]
        rows.append(build_row(cell, d["res"], prompts, corpus, cases, dems, manifest, d["sent"]))
    json.dump(rows, open(os.path.join(config.RESULTS_DIR, "raw", "stage2_rows.json"), "w"),
              indent=2, ensure_ascii=False)
    print("\nbuilt %d rows" % len(rows))
    return rows


if __name__ == "__main__":
    main()

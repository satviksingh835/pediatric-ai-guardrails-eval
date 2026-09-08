#!/usr/bin/env python3
"""Commercial-track generation run (GPT-5.2 via OpenRouter).

Four conditions per (case, demographic, run):
  A  raw                - no checklist
  B  mpnet              - checklist the all-mpnet-base-v2 retriever SELECTED
  B  MiniLM             - checklist the all-MiniLM-L6-v2 retriever SELECTED
  C  oracle             - the GOLD checklist

Retrieval selections are READ from results/retrieval_manifest_frozen.csv. Nothing
is re-embedded or re-ranked: the manifest is the frozen source of truth, so Arm B
reproduces exactly the (possibly wrong) checklist the retriever chose.

Model responses are stored raw - never edited, cleaned, truncated or reformatted.
"""
import csv
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

from guardrail_eval import config
from guardrail_eval.xlsx_io import read_sheet, column_by_prefix

# Pinned dated snapshot. `openai/gpt-5.2` is a moving alias; this is its
# canonical_slug and is accepted directly by the API.
MODEL_PIN = "openai/gpt-5.2-20251211"
PROVIDER = "OpenRouter"
TEMPERATURE = 0.2
MAX_TOKENS = 16000          # generous: reasoning tokens count against this cap
RUNS = 3
URL = "https://openrouter.ai/api/v1/chat/completions"

RETRIEVAL_VERSION = {
    "all-mpnet-base-v2": "frozen-spec-mpnet-v1",
    "all-MiniLM-L6-v2": "frozen-spec-minilm-v1",
}

# (arm, retriever) -> condition label
CONDITIONS = [
    ("A", None),
    ("B", "all-mpnet-base-v2"),
    ("B", "all-MiniLM-L6-v2"),
    ("C", None),
]


# ---------------------------------------------------------------- inputs
def load_prompts():
    """Arm A/B/C prompt bodies, with the sheet's engineer meta-note stripped."""
    out = {}
    for row in read_sheet(config.resolve(config.CASES_FILE), "PROMPTS"):
        label = str(row.get("Arm / setting", "")).strip()
        text = str(row.get("Text (locked)", "")).strip()
        if not label.startswith("Arm"):
            continue
        # Rows for B and C are prefixed with a note to engineers ("SAME prompt
        # text as Arm C. ..."), separated from the real prompt by a blank line.
        if "\n\n" in text:
            text = text.split("\n\n", 1)[1].strip()
        out[label.split()[1]] = text
    assert set(out) >= {"A", "B", "C"}, out.keys()
    assert out["B"] == out["C"], "Arms B and C must share identical prompt text"
    return out


def load_corpus():
    return {r["checklist_id"]: r["checklist_text"]
            for r in read_sheet(config.resolve(config.CORPUS_FILES["locked"]),
                                "GUARDRAIL_CORPUS")
            if str(r.get("checklist_id", "")).startswith("GC-")}


def load_cases():
    out = {}
    for r in read_sheet(config.resolve(config.CASES_FILE), "CASES"):
        cid = str(r.get("base_vignette_id", "")).strip()
        if not cid or cid.startswith("NOTE"):
            continue
        out[cid] = {
            "base_vignette_id": cid,
            "module": r.get("module", ""),
            "case_family": r.get("case_family", ""),
            "difficulty_tier": r.get("difficulty_tier", ""),
            "fairness_eligibility": r.get("fairness_eligibility", ""),
            "vignette_template": r.get("vignette_template", ""),
            "gold_checklist_id": column_by_prefix(r, "gold_checklist_id"),
            "primary_distractor_id": r.get("primary_distractor_id", ""),
        }
    return out


def load_descriptors():
    return {r["demographic_variant_id"]: r["descriptor_to_insert"]
            for r in read_sheet(config.resolve(config.CASES_FILE),
                                "DEMOGRAPHIC_VARIANTS")
            if str(r.get("demographic_variant_id", "")).strip() not in ("", "NOTE")}


def load_manifest():
    """(case, demographic, retriever) -> frozen retrieval row."""
    path = os.path.join(config.RESULTS_DIR, "retrieval_manifest_frozen.csv")
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            out[(r["base_vignette_id"], r["demographic_variant_id"],
                 r["retriever"])] = r
    return out


# ------------------------------------------------------------- assembly
def build_vignette(case, descriptor_text):
    v = case["vignette_template"]
    return v.replace(config.PLACEHOLDER, descriptor_text) if config.PLACEHOLDER in v else v


def build_messages(prompts, corpus, case, vignette, arm, checklist_id):
    """Arm A: prompt + case. Arms B/C: prompt + case + checklist inserted verbatim."""
    if arm == "A":
        content = "%s\n\nCase:\n%s" % (prompts["A"], vignette)
    else:
        checklist = corpus[checklist_id]
        content = "%s\n\nCase:\n%s\n\nSafety checklist:\n%s" % (
            prompts[arm], vignette, checklist)
    return [{"role": "user", "content": content}]


# ----------------------------------------------------------------- call
def call(messages, api_key, model=MODEL_PIN, temperature=TEMPERATURE,
         max_tokens=MAX_TOKENS, max_retries=4, timeout=600):
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "usage": {"include": True},   # ask OpenRouter for billed cost + token detail
    }
    payload = json.dumps(body).encode()
    headers = {"Authorization": "Bearer %s" % api_key,
               "Content-Type": "application/json",
               "X-Title": "Pediatric AI Guardrails - commercial track"}
    last = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(URL, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                d = json.loads(resp.read().decode())
            if "error" in d:
                last = json.dumps(d["error"])[:400]
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return {"status": "error", "error": last, "raw": d}
            ch = d["choices"][0]
            content = ch["message"].get("content") or ""
            finish = ch.get("finish_reason", "")
            u = d.get("usage", {}) or {}
            ctd = u.get("completion_tokens_details", {}) or {}
            status = "ok"
            if not content.strip():
                status = "filtered" if finish == "content_filter" else "empty"
            elif finish == "length":
                status = "truncated"
            return {
                "status": status, "error": "", "content": content,
                "finish_reason": finish,
                "prompt_tokens": u.get("prompt_tokens", 0),
                "completion_tokens": u.get("completion_tokens", 0),
                "reasoning_tokens": ctd.get("reasoning_tokens", 0),
                "total_tokens": u.get("total_tokens", 0),
                "cost": u.get("cost", 0.0),
                "resolved_model": d.get("model", model),
                "provider_name": d.get("provider", ""),
            }
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:400])
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"status": "error", "error": last}
        except (urllib.error.URLError, TimeoutError) as e:
            last = str(e)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"status": "error", "error": last}
    return {"status": "error", "error": last or "unknown"}


def get_key():
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return k


# ------------------------------------------------------------ row build
def make_row(case, dem_id, dem_text, arm, retriever, run_number, run_group_id,
             prompts, corpus, manifest, api_key, live=True):
    vignette = build_vignette(case, dem_text)
    gold = case["gold_checklist_id"]

    if arm == "A":
        checklist_id, mrow = "", None
    elif arm == "C":
        checklist_id, mrow = gold, None
    else:
        mrow = manifest[(case["base_vignette_id"], dem_id, retriever)]
        checklist_id = mrow["selected_checklist_id"]

    messages = build_messages(prompts, corpus, case, vignette, arm, checklist_id)
    res = call(messages, api_key) if live else {"status": "dry", "content": "",
                                                "prompt_tokens": 0, "completion_tokens": 0,
                                                "reasoning_tokens": 0, "cost": 0.0,
                                                "resolved_model": MODEL_PIN,
                                                "finish_reason": "", "error": ""}

    condition = {"A": "A_raw", "C": "C_oracle"}.get(
        arm, "B_%s" % ("mpnet" if retriever == "all-mpnet-base-v2" else "minilm"))

    row = {
        "response_id": str(uuid.uuid4()),
        "blinded_response_code": "R-" + uuid.uuid4().hex[:10].upper(),
        "run_group_id": run_group_id,
        "run_number": run_number,
        "base_vignette_id": case["base_vignette_id"],
        "module": case["module"],
        "case_family": case["case_family"],
        "difficulty_tier": case["difficulty_tier"],
        "demographic_variant_id": dem_id,
        "fairness_eligibility": case["fairness_eligibility"],
        "study_condition": condition,
        "vignette_text": vignette,
        "injected_checklist_id": checklist_id,
        "injected_checklist_text": corpus[checklist_id] if checklist_id else "",
        "model_response": res.get("content", ""),
        # --- retrieval provenance ---
        "retrieval_selected_checklist_id": (mrow["selected_checklist_id"] if mrow else ""),
        "retrieval_gold_checklist_id": gold,
        "retrieval_top3_ids": (mrow["top3_ids"] if mrow else ""),
        "retrieval_top3_scores": ("%s|%s|%s" % (mrow["rank1_score"], mrow["rank2_score"],
                                                mrow["rank3_score"]) if mrow else ""),
        "retrieval_correct": (mrow["retrieval_correct"] if mrow else ""),
        "rank1_minus_rank2_margin": (mrow["rank1_minus_rank2_margin"] if mrow else ""),
        # --- admin ---
        "ADMIN_model_name": MODEL_PIN,
        "ADMIN_model_version": res.get("resolved_model", MODEL_PIN),
        "ADMIN_provider": PROVIDER,
        "ADMIN_study_arm": {"A": "raw", "B": "guardrail", "C": "oracle"}[arm],
        "ADMIN_guardrail_source": {"A": "none", "B": "retrieved", "C": "oracle-gold"}[arm],
        "ADMIN_retrieval_version": (RETRIEVAL_VERSION[retriever] if arm == "B" else ""),
        "ADMIN_guardrail_corpus_version": config.CORPUS_VERSION_LABEL,
        "ADMIN_temperature": TEMPERATURE,
        "ADMIN_run_number": run_number,
        "ADMIN_query_date_time": datetime.now(timezone.utc).isoformat(),
        "ADMIN_prompt_tokens": res.get("prompt_tokens", 0),
        "ADMIN_completion_tokens": res.get("completion_tokens", 0),
        "ADMIN_reasoning_tokens": res.get("reasoning_tokens", 0),
        "ADMIN_cost_usd": res.get("cost", 0.0),
        "ADMIN_finish_reason": res.get("finish_reason", ""),
        "ADMIN_response_status": res.get("status", ""),
        "ADMIN_error": res.get("error", ""),
    }
    return row, res


FIELDS = None  # set from the first row built, preserving insertion order

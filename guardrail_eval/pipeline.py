#!/usr/bin/env python3
"""Shared pipeline logic for the Pediatric AI Guardrails pilot.

- Loads the frozen inputs (inputs.json).
- Assembles the exact prompt sent for a (case, descriptor, arm) combination.
- Enumerates the run plan (the pilot's 66 responses, or the 12-response probe).
- Calls OpenRouter's chat completions API and returns a fully-logged row that
  matches the 22 METADATA_SCHEMA fields.

No prompt wording is changed here; Arm A/B prompt text comes verbatim from the
frozen workbook. Nothing runs on import — callers drive it.
"""
import json
import os
import time
import uuid
import datetime
import urllib.request
import urllib.error

from guardrail_eval import config

HERE = config.REPO_ROOT
INPUTS = config.snapshot_path()

# ---- run configuration (locked pilot parameters; single source in config.py) ----
MODEL = config.GEN_MODEL
PROVIDER = config.GEN_PROVIDER
TEMPERATURE = config.GEN_TEMPERATURE
RUNS = config.GEN_RUNS
ARMS = config.GEN_ARMS

# Version tags recorded per response so the frozen config is auditable.
GUARDRAIL_VERSION = "v2"          # checklist text comes from Data Package v2
RETRIEVAL_VERSION = "keyed-lookup-v1"  # exact case_id -> checklist mapping
SYSTEM_PROMPT_VERSION = "v2"      # locked PROMPTS sheet, Data Package v2

ARM_STUDY_LABEL = {"A": "raw", "B": "guardrail"}  # ADMIN_study_arm values

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_inputs(path=INPUTS):
    with open(path) as f:
        return json.load(f)


def get_api_key():
    """Read the lab's OpenRouter key from the environment (never hardcoded)."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Provide the lab key, e.g.:\n"
            "  export OPENROUTER_API_KEY=sk-or-...   (or add it to a .env you source)")
    return key


# --------------------------------------------------------------------------
# Prompt assembly
# --------------------------------------------------------------------------
def build_vignette(case, descriptor, placeholder):
    """Insert the descriptor into the template. B6.2 has no placeholder -> unchanged."""
    template = case["vignette_template"]
    if case["has_placeholder"] and descriptor is not None:
        return template.replace(placeholder, descriptor["descriptor_to_insert"])
    return template


def build_messages(inputs, case, descriptor, arm):
    """Return the exact message list sent to the model for this combination.

    Arm A: raw prompt + vignette.
    Arm B: guardrail prompt + vignette + this case's checklist (keyed lookup).
    """
    vignette = build_vignette(case, descriptor, inputs["placeholder"])
    if arm == "A":
        instruction = inputs["prompts"]["A"]
        user = "%s\n\nCase:\n%s" % (instruction, vignette)
    elif arm == "B":
        instruction = inputs["prompts"]["B"]
        checklist = case["guardrail_checklist_arm_B"]
        user = "%s\n\nCase:\n%s\n\nSafety checklist:\n%s" % (instruction, vignette, checklist)
    else:
        raise ValueError("Unknown arm %r" % arm)
    return [{"role": "user", "content": user}], vignette


# --------------------------------------------------------------------------
# Run plan enumeration
# --------------------------------------------------------------------------
def enumerate_combinations(inputs, runs=RUNS, arms=ARMS):
    """Yield every (case, descriptor_or_None, arm, run_number) for the pilot.

    Swap-eligible cases run once per descriptor; B6.2 (no placeholder) runs once
    with descriptor=None and is excluded from the race counterfactual by design.
    """
    combos = []
    for case in inputs["pilot_cases"]:
        descriptors = inputs["pilot_descriptors"] if case["has_placeholder"] else [None]
        for descriptor in descriptors:
            for arm in arms:
                for run in range(1, runs + 1):
                    combos.append((case, descriptor, arm, run))
    return combos


def enumerate_probe(inputs, arms=ARMS):
    """12-response cost probe: each of the 6 cases x both arms x 1 run.

    One unique prompt per case/arm (descriptor held to the first pilot descriptor
    for swap-eligible cases; None for B6.2). Token usage of these 12 extrapolates
    to the full 66 since the descriptor swap and runs 2-3 barely change lengths.
    """
    combos = []
    first_desc = inputs["pilot_descriptors"][0]
    for case in inputs["pilot_cases"]:
        descriptor = first_desc if case["has_placeholder"] else None
        for arm in arms:
            combos.append((case, descriptor, arm, 1))
    return combos


# --------------------------------------------------------------------------
# Model call
# --------------------------------------------------------------------------
def call_openrouter(messages, api_key, model=MODEL, temperature=TEMPERATURE,
                    max_retries=4, timeout=120):
    """POST to OpenRouter. Returns (content, usage_dict, model_version, status, error)."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }).encode("utf-8")
    headers = {
        "Authorization": "Bearer %s" % api_key,
        "Content-Type": "application/json",
        "X-Title": "Pediatric AI Guardrails Pilot",
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(OPENROUTER_URL, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = data["choices"][0]
            content = choice["message"]["content"]
            finish = choice.get("finish_reason", "")
            usage = data.get("usage", {}) or {}
            model_version = data.get("model", model)
            status = "ok"
            if content is None or content == "":
                status = "filtered" if finish == "content_filter" else "error"
            return content or "", usage, model_version, status, ""
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            last_err = "HTTP %s: %s" % (e.code, body[:500])
            # 429/5xx are transient; back off and retry.
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return "", {}, model, "error", last_err
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = str(e)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return "", {}, model, "error", last_err
    return "", {}, model, "error", last_err or "unknown"


# --------------------------------------------------------------------------
# Row building (22 METADATA_SCHEMA fields)
# --------------------------------------------------------------------------
def build_row(inputs, case, descriptor, arm, run, api_key, live=True):
    """Assemble the prompt, (optionally) call the model, return a full metadata row."""
    messages, vignette = build_messages(inputs, case, descriptor, arm)
    if live:
        content, usage, model_version, status, error = call_openrouter(messages, api_key)
    else:
        content, usage, model_version, status, error = "", {}, "(dry-run)", "dry-run", ""

    race = descriptor["race_ethnicity"] if descriptor else ""
    gender = descriptor["gender_descriptor"] if descriptor else ""
    variant_id = descriptor["demographic_variant_id"] if descriptor else "NONE"

    row = {
        "response_id": str(uuid.uuid4()),
        "blinded_response_code": _blinded_code(),
        "base_vignette_id": case["base_vignette_id"],
        "module": case["module"],
        "case_family": case["case_family"],
        "demographic_variant_id": variant_id,
        "fairness_eligibility": case["fairness_eligibility"],
        "vignette_text": vignette,
        "model_response": content,
        "ADMIN_model_name": MODEL,
        "ADMIN_model_version": model_version,
        "ADMIN_provider": PROVIDER,
        "ADMIN_study_arm": ARM_STUDY_LABEL[arm],
        "ADMIN_retrieval_version": RETRIEVAL_VERSION if arm == "B" else "",
        "ADMIN_guardrail_version": GUARDRAIL_VERSION if arm == "B" else "",
        "ADMIN_race_ethnicity": race,
        "ADMIN_gender_descriptor": gender,
        "ADMIN_run_number": run,
        "ADMIN_query_date_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ADMIN_temperature": TEMPERATURE,
        "ADMIN_system_prompt_version": SYSTEM_PROMPT_VERSION,
        "ADMIN_response_status": status,
    }
    return row, usage, error


def _blinded_code():
    """Opaque random code the reviewers see; PI re-links via the unblinding key."""
    return "R-" + uuid.uuid4().hex[:10].upper()

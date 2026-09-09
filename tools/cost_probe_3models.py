#!/usr/bin/env python3
"""Cost probe: 4 conditions on A1.1 / first descriptor / run 1, per model.

Conditions: Arm A raw | Arm B mpnet-primary | Arm B MiniLM-primary | Arm C oracle
Retrieval selections are READ from retrieval_manifest_allergy_v2_final.csv
(primary_frozen), never recomputed.
"""
import csv, json, os, sys, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from guardrail_eval import config
from guardrail_eval.xlsx_io import read_sheet, column_by_prefix

PKG = "data/Engineering_Data_Package_ALLERGY_FULL_FINAL_v2.xlsx"
MANIFEST = os.path.join(config.RESULTS_DIR, "retrieval_manifest_allergy_v2_final.csv")
URL = "https://openrouter.ai/api/v1/chat/completions"
TEMP, MAXTOK = 0.2, 16000
PLACEHOLDER = "[DEMOGRAPHIC DESCRIPTOR]"


def prompts():
    out = {}
    for r in read_sheet(PKG, "PROMPTS"):
        vals = list(r.values())
        lab, txt = str(vals[0]).strip(), str(vals[1]).strip()
        if not lab.startswith("Arm"):
            continue
        if "\n\n" in txt:            # strip engineer meta-note if present
            txt = txt.split("\n\n", 1)[1].strip()
        out[lab.split()[1]] = txt
    return out


def corpus():
    return {r["checklist_id"]: r["checklist_text"]
            for r in read_sheet(PKG, "GUARDRAIL_CORPUS")
            if str(r.get("checklist_id", "")).startswith("GC-")}


def call(model, messages, key, temperature=TEMP, max_tokens=MAXTOK, n_retry=3):
    body = json.dumps({"model": model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens,
                       "usage": {"include": True}}).encode()
    hdr = {"Authorization": "Bearer %s" % key, "Content-Type": "application/json",
           "X-Title": "Pediatric AI Guardrails - allergy cost probe"}
    for a in range(n_retry):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(URL, data=body, headers=hdr), timeout=600) as r:
                d = json.loads(r.read().decode())
            if "error" in d:
                return {"status": "error", "error": json.dumps(d["error"])[:300]}
            ch = d["choices"][0]
            u = d.get("usage", {}) or {}
            ctd = u.get("completion_tokens_details", {}) or {}
            content = ch["message"].get("content") or ""
            return {"status": "ok" if content.strip() else "empty",
                    "content": content, "finish": ch.get("finish_reason", ""),
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "reasoning_tokens": ctd.get("reasoning_tokens", 0),
                    "cost": u.get("cost", 0.0), "echo": d.get("model", ""),
                    "provider": d.get("provider", ""), "error": ""}
        except urllib.error.HTTPError as e:
            err = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
            if e.code in (429, 500, 502, 503, 504) and a < n_retry - 1:
                import time; time.sleep(2 ** a); continue
            return {"status": "error", "error": err}
        except Exception as e:
            if a < n_retry - 1:
                import time; time.sleep(2 ** a); continue
            return {"status": "error", "error": str(e)}


def main(models):
    key = os.environ["OPENROUTER_API_KEY"]
    P, C = prompts(), corpus()
    cases = {r["base_vignette_id"]: r for r in read_sheet(PKG, "CASES")}
    dv = [r for r in read_sheet(PKG, "DEMOGRAPHIC_VARIANTS")
          if str(r.get("demographic_variant_id", "")).strip() not in ("", "NOTE")]
    case, dem = cases["A1.1"], dv[0]
    gold = column_by_prefix(case, "gold_checklist_id")
    vign = case["vignette_template"].replace(PLACEHOLDER, dem["descriptor_to_insert"])

    sel = {}
    with open(MANIFEST) as f:
        for r in csv.DictReader(f):
            if (r["base_vignette_id"] == "A1.1"
                    and r["demographic_variant_id"] == dem["demographic_variant_id"]
                    and r["indexing_variant"] == "primary_frozen"):
                sel[r["retriever"]] = r["selected_checklist_id"]

    conds = [("A_raw", "A", ""),
             ("B_mpnet_primary", "B", sel["all-mpnet-base-v2"]),
             ("B_minilm_primary", "B", sel["all-MiniLM-L6-v2"]),
             ("C_oracle", "C", gold)]

    out = {}
    for label, mid in models:
        print("\n### %s  (%s)" % (label, mid), flush=True)
        rows = []
        for cname, arm, inj in conds:
            if arm == "A":
                msg = "%s\n\nCase:\n%s" % (P["A"], vign)
            else:
                msg = "%s\n\nCase:\n%s\n\nSafety checklist:\n%s" % (P[arm], vign, C[inj])
            r = call(mid, [{"role": "user", "content": msg}], key)
            r.update(condition=cname, injected=inj or "(none)")
            rows.append(r)
            print("  %-17s %-7s inj=%-20s p=%-6s c=%-6s r=%-6s $%.6f %s"
                  % (cname, r["status"], r["injected"], r.get("prompt_tokens"),
                     r.get("completion_tokens"), r.get("reasoning_tokens"),
                     r.get("cost", 0), r.get("error", "")[:70]), flush=True)
        out[label] = {"model_id": mid, "rows": rows}

    # empirical temperature check: identical prompt x5 at temp 0.2
    print("\n### empirical temperature check (identical prompt x5 @ temp 0.2)")
    for label, mid in models:
        outs, cost = [], 0.0
        for _ in range(5):
            r = call(mid, [{"role": "user", "content":
                            "Name one random animal. Reply with only the animal name."}],
                     key, max_tokens=3000)
            outs.append((r.get("content") or "").strip()[:24]); cost += r.get("cost", 0)
        uniq = len({o.lower() for o in outs})
        out[label]["temp_test"] = {"outputs": outs, "unique": uniq, "cost": cost}
        print("  %-16s %-52s unique=%d/5  $%.5f"
              % (label, str(outs), uniq, cost), flush=True)

    dst = os.path.join(config.RESULTS_DIR, "raw", "allergy_cost_probe.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    json.dump(out, open(dst, "w"), indent=2, ensure_ascii=False)
    print("\nwrote %s" % dst)


if __name__ == "__main__":
    # Pinned dated snapshots (canonical_slug). The API echoes back the undated
    # alias, so the sent pin and the echo are logged separately.
    MODELS = [("GPT-5.2", "openai/gpt-5.2-20251211"),
              ("Gemini 3.1 Pro", "google/gemini-3.1-pro-preview-20260219"),
              ("Claude Opus 5", "anthropic/claude-opus-5-20260723")]
    main(MODELS)

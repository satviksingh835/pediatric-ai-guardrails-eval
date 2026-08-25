"""Paths and locked run parameters.

Data files live under `data/` and are resolved relative to the repository root,
so nothing depends on a particular machine's home directory. The collaboration's
real corpus is embargoed (see docs/DATA_AVAILABILITY.md); set GUARDRAIL_DATA_DIR
to point at it, otherwise the synthetic fixture under data/synthetic is used so
the pipeline is runnable out of the box.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("GUARDRAIL_DATA_DIR", os.path.join(REPO_ROOT, "data"))
PRIVATE_DIR = os.path.join(DATA_DIR, "private")
SYNTHETIC_DIR = os.path.join(DATA_DIR, "synthetic")
RESULTS_DIR = os.environ.get("GUARDRAIL_RESULTS_DIR", os.path.join(REPO_ROOT, "results"))

# Corpus revisions. v3/v4 differ only in GC-ANA and GC-HAE (see docs/RESULTS.md).
CORPUS_FILES = {
    "v3": "Engineering_Data_Package_PILOT_v3.xlsx",
    "v4": "Engineering_Data_Package_PILOT_v4.xlsx",
    "locked": "Guardrail_Corpus_v4_FINAL_LOCKED.xlsx",
}
CASES_FILE = "Engineering_Data_Package_PILOT_v4.xlsx"
DATA_PACKAGE_FILE = "Pediatric_AI_Guardrails_Engineering_Data_Package.xlsx"

# The pilot's locked subset. If none of these ids are present (e.g. when running
# against the synthetic fixture) every case/descriptor in the sheet is used.
PILOT_CASE_IDS = ["A1.1", "A3.1", "A3.3", "B2.3", "B4.2", "B6.2"]
PILOT_DESCRIPTOR_IDS = ["WHI_M", "BLA_M"]


def resolve(filename):
    """Prefer the embargoed real data if present, else the synthetic fixture."""
    private = os.path.join(PRIVATE_DIR, filename)
    if os.path.exists(private):
        return private
    synthetic = os.path.join(SYNTHETIC_DIR, filename)
    if os.path.exists(synthetic):
        return synthetic
    raise FileNotFoundError(
        "%s not found in %s or %s. See docs/DATA_AVAILABILITY.md."
        % (filename, PRIVATE_DIR, SYNTHETIC_DIR))


def using_synthetic(filename):
    return not os.path.exists(os.path.join(PRIVATE_DIR, filename))


def snapshot_path():
    """Where freeze_inputs writes inputs.json: beside the corpus it snapshotted.

    A snapshot of the embargoed corpus is itself embargoed, so it lands in
    private/ and is gitignored. A snapshot of the fixture is harmless.
    """
    base = SYNTHETIC_DIR if using_synthetic(CASES_FILE) else PRIVATE_DIR
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "inputs.json")


# ---- locked experimental parameters (do not change mid-study) ----
PLACEHOLDER = "[DEMOGRAPHIC DESCRIPTOR]"
RETRIEVERS = ["all-mpnet-base-v2", "all-MiniLM-L6-v2"]
CORPUS_VERSION_LABEL = "guardrail_corpus_v4_32items"

GEN_MODEL = "meta-llama/llama-3.3-70b-instruct"
GEN_PROVIDER = "OpenRouter"
GEN_TEMPERATURE = 0.2
GEN_RUNS = 3
GEN_ARMS = ["A", "B"]

MANIFEST_FIELDS = [
    "retriever", "corpus_version", "base_vignette_id", "demographic_variant_id",
    "difficulty_tier", "gold_checklist_id", "primary_distractor_id",
    "selected_checklist_id", "rank1_score", "rank2_score", "rank3_score",
    "top3_ids", "rank1_minus_rank2_margin", "retrieval_correct",
]

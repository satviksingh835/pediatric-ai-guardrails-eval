#!/usr/bin/env python3
"""CSV writer for pilot response rows (one row per response, 22 schema columns)."""
import csv
from guardrail_eval import pipeline as P


def write_csv(rows, path, inputs=None):
    fields = (inputs or P.load_inputs())["metadata_fields"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path

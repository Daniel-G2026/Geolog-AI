"""Verify a corpus of synthetic logs covers every cell in the failure-mode matrix.

Usage:
    python -m tools.assert_coverage --dir fixtures/

Reads every *.ground_truth.json under --dir, unions every sample's
`scenarios` list, and asserts each required tag appears at least once.
Exits non-zero with a punch-list if anything is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Set


REQUIRED_SCENARIOS: Set[str] = {
    "refusal_explicit_notation",
    "refusal_no_notation",
    "split_2_layer",
    "split_3_layer",
    "recovery_partial",
    "recovery_missing",
    "color_missing",
    "lab_sparse",
    "lab_dense",
    "particle_size_modifier",
    "astm_descriptor",
}


def collect_scenarios(corpus_dir: Path) -> Set[str]:
    found: Set[str] = set()
    for gt in corpus_dir.glob("*.ground_truth.json"):
        data = json.loads(gt.read_text())
        for s in data.get("samples", []):
            for tag in s.get("scenarios", []):
                found.add(tag)
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, required=True)
    args = p.parse_args()
    found = collect_scenarios(args.dir)
    missing = REQUIRED_SCENARIOS - found
    extra = found - REQUIRED_SCENARIOS
    print(f"Corpus dir: {args.dir}")
    print(f"Found {len(found)} unique scenario tags.")
    if extra:
        print(f"Extra (informational): {sorted(extra)}")
    if missing:
        print(f"MISSING required scenarios: {sorted(missing)}", file=sys.stderr)
        sys.exit(1)
    print("OK — every required scenario tag is covered.")


if __name__ == "__main__":
    main()

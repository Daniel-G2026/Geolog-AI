"""CLI: synthesize one borehole log (PDF + ground-truth JSON) per seed.

Usage:
    python -m tools.generate_synthetic_log --seed 42 --firm firma --out fixtures/

Produces:
    fixtures/42.pdf
    fixtures/42.ground_truth.json

Scope (Chunk 3): sample-driven logs only, 2 generic firm styles.
Stratigraphic + hybrid + real firm styles deferred to Chunk 3b / 5.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List

from tools.firm_styles import FIRM_STYLES, get_firm
from tools.pdf_renderer import render_pdf
from tools.soil_corpus import SyntheticSample, roll_sample


# ── Scenario weights per sample ──
# A single synthetic log is a sequence of samples, each rolled with weighted
# odds so that across many seeds the corpus covers the matrix.

SCENARIO_WEIGHTS = {
    "refusal":   [("none", 0.80), ("explicit_notation", 0.12), ("no_notation", 0.08)],
    "split":     [("none", 0.65), ("two_layer", 0.25), ("three_layer", 0.10)],
    "recovery":  [("full", 0.55), ("partial", 0.30), ("missing", 0.15)],
    "lab_data":  [("none", 0.45), ("sparse", 0.40), ("dense", 0.15)],
}


def _weighted_choice(rng: random.Random, choices):
    r = rng.random()
    cum = 0.0
    for value, w in choices:
        cum += w
        if r <= cum:
            return value
    return choices[-1][0]


def build_borehole(rng: random.Random, seed: int) -> Dict[str, Any]:
    """Synthesize the borehole header — every Chunk 2 field present."""
    return {
        "borehole_no": f"SYN-{seed:04d}",
        "project_no": f"PROJ-{rng.randint(100, 999)}",
        "location": rng.choice(["Toronto, ON", "Hamilton, ON", "Windsor, ON"]),
        "tech": rng.choice(["Daniel", "Alex", "Jordan"]),
        "drilling_method": rng.choice(["Hollow Stem Auger", "Solid Stem Auger"]),
        "date_started": "2026-05-22",
        "driller": rng.choice(["Davis", "Spencer", "Boart"]),
        # Chunk 2 fields:
        "latitude":  round(43.0 + rng.random(), 4),
        "longitude": round(-79.0 - rng.random(), 4),
        "ground_elevation_ft": round(rng.uniform(200, 350), 1),
        "datum": rng.choice(["NAD83", "NAVD88"]),
        "depth_reference_datum": "ground surface",
        "total_depth_ft": None,        # filled after samples are rolled
        "termination_reason": None,    # filled after samples
        "groundwater": rng.choice([
            None,
            {"encountered_ft": round(rng.uniform(3, 15), 1),
             "stabilized_ft": round(rng.uniform(2, 14), 1),
             "date_measured": "2026-05-22", "dry": False},
            {"dry": True},
        ]),
        "hammer_type": rng.choice(["automatic", "safety", "donut"]),
        "hammer_efficiency": round(rng.uniform(0.6, 0.95), 2),
        "sampler_id": "SS-2in",
        "borehole_diameter_in": rng.choice([4.0, 6.0]),
    }


def build_samples(rng: random.Random, n_samples: int = 8) -> List[SyntheticSample]:
    samples: List[SyntheticSample] = []
    depth = 0.5
    for i in range(1, n_samples + 1):
        refusal = _weighted_choice(rng, SCENARIO_WEIGHTS["refusal"])
        split = _weighted_choice(rng, SCENARIO_WEIGHTS["split"])
        recovery = _weighted_choice(rng, SCENARIO_WEIGHTS["recovery"])
        lab_data = _weighted_choice(rng, SCENARIO_WEIGHTS["lab_data"])
        color_missing = rng.random() < 0.15
        force_ps = True if rng.random() < 0.35 else None
        force_astm = rng.random() < 0.35

        s = roll_sample(
            rng,
            sample_no=i,
            depth_ft=round(depth, 1),
            refusal=refusal,
            split=split,
            recovery=recovery,
            color_missing=color_missing,
            lab_data=lab_data,
            force_particle_size=force_ps,
            force_astm_descriptor=force_astm,
        )
        samples.append(s)
        # Advance depth: sample length + 0.5–2 ft of auger advance
        depth += sum(s.pen_depths) / 12.0 + rng.uniform(0.5, 2.0)
        if s.refusal:
            break  # stop drilling at refusal
    return samples


def write_artifacts(seed: int, firm_name: str, out_dir: Path):
    rng = random.Random(seed)
    firm = get_firm(firm_name)

    borehole = build_borehole(rng, seed)
    samples = build_samples(rng)

    # Backfill borehole totals now that samples exist.
    total_depth = max(s.depth_ft + sum(s.pen_depths) / 12.0 for s in samples)
    borehole["total_depth_ft"] = round(total_depth, 1)
    borehole["termination_reason"] = "refusal" if samples[-1].refusal else "planned_depth"

    pdf_bytes = render_pdf(borehole, samples, firm)
    ground_truth = {
        "seed": seed,
        "firm": firm.firm_name,
        "borehole": borehole,
        "samples": [s.to_ground_truth() for s in samples],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{seed}.pdf"
    json_path = out_dir / f"{seed}.ground_truth.json"
    pdf_path.write_bytes(pdf_bytes)
    json_path.write_text(json.dumps(ground_truth, indent=2, default=str))
    return pdf_path, json_path


def main():
    p = argparse.ArgumentParser(description="Generate one synthetic borehole log + ground truth.")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--firm", choices=sorted(FIRM_STYLES.keys()), default="firma")
    p.add_argument("--out", type=Path, default=Path("fixtures"))
    args = p.parse_args()

    pdf_path, json_path = write_artifacts(args.seed, args.firm, args.out)
    print(f"wrote: {pdf_path}")
    print(f"wrote: {json_path}")


if __name__ == "__main__":
    main()

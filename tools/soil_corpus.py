"""Soil sampling corpus for the synthetic borehole log generator.

Generates random-but-plausible soil samples. Records the structured ground
truth FIRST (every Chunk 1 field), then formats the prose for the PDF. This
ordering guarantees the PDF and the ground-truth JSON cannot drift.

Coverage hooks are exposed via `roll_sample(scenario=...)` so the CLI can
ensure a corpus exercises every cell of the failure-mode matrix:

  refusal              — "50/3" notation, no-notation refusal, normal
  split_layers         — none, 2-layer, 3-layer
  recovery             — full, partial, missing
  color_missing        — color present vs not stated
  lab_data             — none, sparse (~30%), dense
  particle_size        — none, "fine", "medium to coarse", etc.
  astm_descriptor      — angularity, cementation, HCl reaction sprinkled in
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Vocabulary (anchored on the pipeline's valid soil names) ──

COHESIVE_SOILS = ["silty clay", "clayey silt", "silt", "clay"]
COHESIONLESS_SOILS = ["silty sand", "sandy silt", "sand and gravel", "sand"]
ALL_SOILS = COHESIVE_SOILS + COHESIONLESS_SOILS

# Maps each primary soil to a plausible USCS symbol (deterministic for ground truth).
USCS_BY_SOIL = {
    "silty clay":     "CL",
    "clayey silt":    "ML",
    "silt":           "ML",
    "clay":           "CL",
    "silty sand":     "SM",
    "sandy silt":     "ML",
    "sand and gravel":"SW",
    "sand":           "SP",
}

COLORS = ["brown", "dark brown", "grey", "light grey", "reddish brown", "tan", "black"]
MOISTURES = ["dry", "moist", "wet", "very moist"]

# Particle-size modifiers only attach to sand or gravel-containing soils.
PARTICLE_SIZE_TARGETS = {"sand", "sand and gravel"}
PARTICLE_SIZE_RANGES = ["fine", "medium", "coarse", "fine to medium", "medium to coarse"]

# ASTM D2488 catch-all descriptors that should land in `descriptor_fields`.
ASTM_DESCRIPTORS = {
    "angularity":     ["subangular", "angular", "subrounded", "rounded"],
    "cementation":    ["weak", "moderate", "strong"],
    "hcl_reaction":   ["none", "weak", "strong"],
    "max_particle_size": ["coarse sand", "fine gravel", "coarse gravel"],
}

COMPONENTS_BY_SOIL = {
    "silty clay": ["trace sand", "trace gravel", "some sand"],
    "clayey silt": ["trace sand", "some clay"],
    "silt": ["trace clay", "trace sand"],
    "clay": ["trace silt", "trace sand"],
    "silty sand": ["trace gravel", "some silt"],
    "sandy silt": ["trace clay"],
    "sand and gravel": ["trace silt"],
    "sand": ["trace gravel", "some gravel"],
}

INCLUSIONS_POOL = [
    "rootlets", "organic inclusions", "rock fragments",
    "concrete fragments", "oxidation",
]


@dataclass
class SyntheticSample:
    """Mirrors what pipeline.combination() should produce for this sample."""

    sample_no: int
    depth_ft: float

    # SPT / recovery
    blow_counts: List[int]
    pen_depths: List[float]
    n_value: int
    n_value_log: str
    refusal: bool
    recovery_inches: Optional[float]

    # Chunk 1 structured fields
    soil_name: Optional[str]
    particle_size_range: Optional[str]
    color: Optional[str]
    moisture: Optional[str]
    plasticity: Optional[str]
    gradation: Optional[str]
    consistency: Optional[str]
    density: Optional[str]
    uscs_symbol: Optional[str]
    fill: bool
    inclusions: List[str]
    components: List[str]
    descriptor_fields: Dict[str, str]
    layers: Optional[List[Dict[str, Any]]]   # split-layer JSONB shape
    lab_tests: Optional[Dict[str, Any]]

    # Description prose rendered into the PDF (formatted from the fields above).
    description: str

    # Scenario tags this sample exercises — used by assert_coverage.
    scenarios: List[str] = field(default_factory=list)

    def to_ground_truth(self) -> Dict[str, Any]:
        return {
            "sample_no": self.sample_no,
            "depth_ft": self.depth_ft,
            "blow_counts": self.blow_counts,
            "pen_depths": self.pen_depths,
            "n_value": self.n_value,
            "n_value_log": self.n_value_log,
            "refusal": self.refusal,
            "recovery_inches": self.recovery_inches,
            "soil_name": self.soil_name,
            "particle_size_range": self.particle_size_range,
            "color": self.color,
            "moisture": self.moisture,
            "plasticity": self.plasticity,
            "gradation": self.gradation,
            "consistency": self.consistency,
            "density": self.density,
            "uscs_symbol": self.uscs_symbol,
            "fill": self.fill,
            "inclusions": self.inclusions,
            "components": self.components,
            "descriptor_fields": self.descriptor_fields,
            "layers": self.layers,
            "lab_tests": self.lab_tests,
            "description": self.description,
            "scenarios": sorted(self.scenarios),
        }


# ── Helper roll functions ──

def _roll_blow_counts(rng: random.Random, refusal_mode: str):
    """Returns (blow_counts, pen_depths, n_value, n_value_log, refusal_bool)."""
    if refusal_mode == "explicit_notation":
        # "50/3" — 50 blows in 3 inches mid-sample. Mimic what parse_blow_counts
        # would produce: pen_depths = [6, 3], blow_counts = [25, 50].
        blow_counts = [rng.randint(15, 30), 50]
        pen_depths = [6.0, 3.0]
        n_value = blow_counts[0] + 50
        n_value_log = f"{blow_counts[0]}/50/3\""
        return blow_counts, pen_depths, n_value, n_value_log, True
    if refusal_mode == "no_notation":
        # High blow count without explicit "/3" notation — requires fallback.
        blow_counts = [rng.randint(20, 40), rng.randint(45, 60), rng.randint(50, 60)]
        pen_depths = [6.0, 6.0, 6.0]
        middle_two = sum(blow_counts[-2:])
        return blow_counts, pen_depths, middle_two, "/".join(str(b) for b in blow_counts), False
    # Normal sample
    blow_counts = [rng.randint(2, 12) for _ in range(4)]
    pen_depths = [6.0] * 4
    n_value = blow_counts[1] + blow_counts[2]
    n_value_log = "/".join(str(b) for b in blow_counts)
    return blow_counts, pen_depths, n_value, n_value_log, False


def _classify_consistency_density(soil_name: str, n_value: int):
    """Mirrors classification_engine.consistency_density_condition outputs.

    Returns (consistency, density) where exactly one is populated for soils
    we recognise. Falls back to (None, None) for anything not in the lookup
    (which the harness will treat as 'pipeline should produce manual review').
    """
    cohesive = soil_name in COHESIVE_SOILS
    cohesionless = soil_name in COHESIONLESS_SOILS

    if cohesive:
        if n_value < 2:   term = "very soft"
        elif n_value < 4: term = "soft"
        elif n_value < 8: term = "firm"
        elif n_value < 15: term = "stiff"
        elif n_value < 30: term = "very stiff"
        else: term = "hard"
        return term, None
    if cohesionless:
        if n_value < 4:   term = "very loose"
        elif n_value < 10: term = "loose"
        elif n_value < 30: term = "compact"
        elif n_value < 50: term = "dense"
        else: term = "very dense"
        return None, term
    return None, None


def _format_description(
    *,
    fill: bool,
    particle_size: Optional[str],
    soil_name: str,
    uscs: Optional[str],
    components: List[str],
    inclusions: List[str],
    color: Optional[str],
    moisture: Optional[str],
    consistency: Optional[str],
    density: Optional[str],
) -> str:
    parts: List[str] = []
    if fill:
        parts.append("Fill,")

    head = soil_name
    if particle_size:
        head = f"{particle_size} {soil_name}"
    head = head[0].upper() + head[1:]
    if uscs:
        head = f"{head} ({uscs})"
    parts.append(head)

    for c in components:
        parts.append(f"with {c}" if "with " not in c else c)
    for inc in inclusions:
        parts.append(inc)
    if color:
        parts.append(color)
    if moisture:
        parts.append(moisture)
    if consistency:
        parts.append(consistency)
    elif density:
        parts.append(density)

    return ", ".join(parts).rstrip(",") + "."


def _maybe_lab_tests(rng: random.Random, lab_mode: str) -> Optional[Dict[str, Any]]:
    if lab_mode == "none":
        return None
    if lab_mode == "sparse" and rng.random() > 0.35:
        return None
    return {
        "moisture_content_pct": round(rng.uniform(8, 35), 1),
        "atterberg": {
            "ll": rng.randint(20, 60),
            "pl": rng.randint(12, 30),
            "pi": rng.randint(5, 30),
        },
        "grain_size_pct": {
            "gravel": rng.randint(0, 40),
            "sand":   rng.randint(20, 80),
            "fines":  rng.randint(0, 60),
        },
    }


# ── Single-sample roller ──

def roll_sample(
    rng: random.Random,
    *,
    sample_no: int,
    depth_ft: float,
    refusal: str = "none",                   # none | explicit_notation | no_notation
    split: str = "none",                     # none | two_layer | three_layer
    recovery: str = "full",                  # full | partial | missing
    color_missing: bool = False,
    lab_data: str = "none",                  # none | sparse | dense
    force_particle_size: Optional[bool] = None,
    force_astm_descriptor: bool = False,
    fill_chance: float = 0.05,
) -> SyntheticSample:
    """Generate one sample with the requested scenarios baked in."""
    scenarios: List[str] = []

    # Pick blow counts + refusal flag.
    blow_counts, pen_depths, n_value, n_value_log, refusal_bool = _roll_blow_counts(rng, refusal)
    if refusal != "none":
        scenarios.append(f"refusal_{refusal}")

    # Recovery.
    total_pen = sum(pen_depths)
    if recovery == "missing":
        recovery_inches = None
        scenarios.append("recovery_missing")
    elif recovery == "partial":
        recovery_inches = round(total_pen * rng.uniform(0.3, 0.7), 1)
        scenarios.append("recovery_partial")
    else:
        recovery_inches = round(total_pen, 1)

    fill = rng.random() < fill_chance
    if fill:
        scenarios.append("fill")

    # Build the soil descriptor — single soil or split-layer.
    layers: Optional[List[Dict[str, Any]]] = None
    if split == "none":
        primary = rng.choice(ALL_SOILS)
        sample_truth = _build_single_layer(
            rng,
            soil_name=primary,
            n_value=n_value,
            color_missing=color_missing,
            force_particle_size=force_particle_size,
            force_astm_descriptor=force_astm_descriptor,
        )
    else:
        layer_count = 2 if split == "two_layer" else 3
        scenarios.append(f"split_{layer_count}_layer")
        sample_truth, layers = _build_split_layers(
            rng,
            layer_count=layer_count,
            n_value=n_value,
            color_missing=color_missing,
            force_particle_size=force_particle_size,
            force_astm_descriptor=force_astm_descriptor,
            recovery_inches=recovery_inches if recovery_inches is not None else total_pen,
        )

    if sample_truth["particle_size_range"]:
        scenarios.append("particle_size_modifier")
    if sample_truth["descriptor_fields"]:
        scenarios.append("astm_descriptor")
    if color_missing:
        scenarios.append("color_missing")

    lab_tests = _maybe_lab_tests(rng, lab_data)
    if lab_tests:
        scenarios.append(f"lab_{lab_data}")

    desc = sample_truth["description"]
    if layers is not None:
        # Description for split-layer samples = " / ".join(layer descriptions)
        desc = " / ".join(lf["description"] for lf in layers)

    return SyntheticSample(
        sample_no=sample_no,
        depth_ft=depth_ft,
        blow_counts=blow_counts,
        pen_depths=pen_depths,
        n_value=n_value,
        n_value_log=n_value_log,
        refusal=refusal_bool,
        recovery_inches=recovery_inches,
        soil_name=sample_truth["soil_name"],
        particle_size_range=sample_truth["particle_size_range"],
        color=sample_truth["color"],
        moisture=sample_truth["moisture"],
        plasticity=sample_truth["plasticity"],
        gradation=sample_truth["gradation"],
        consistency=sample_truth["consistency"],
        density=sample_truth["density"],
        uscs_symbol=sample_truth["uscs_symbol"],
        fill=fill,
        inclusions=sample_truth["inclusions"],
        components=sample_truth["components"],
        descriptor_fields=sample_truth["descriptor_fields"],
        layers=layers,
        lab_tests=lab_tests,
        description=desc,
        scenarios=scenarios,
    )


def _build_single_layer(
    rng: random.Random,
    *,
    soil_name: str,
    n_value: int,
    color_missing: bool,
    force_particle_size: Optional[bool],
    force_astm_descriptor: bool,
) -> Dict[str, Any]:
    uscs = USCS_BY_SOIL.get(soil_name)
    color = None if color_missing else rng.choice(COLORS)
    moisture = rng.choice(MOISTURES)
    consistency, density = _classify_consistency_density(soil_name, n_value)

    particle_size = None
    if soil_name in PARTICLE_SIZE_TARGETS:
        want = force_particle_size if force_particle_size is not None else (rng.random() < 0.5)
        if want:
            particle_size = rng.choice(PARTICLE_SIZE_RANGES)

    components = []
    pool = COMPONENTS_BY_SOIL.get(soil_name, [])
    if pool and rng.random() < 0.6:
        components = [rng.choice(pool)]

    inclusions: List[str] = []
    if rng.random() < 0.25:
        inclusions = [rng.choice(INCLUSIONS_POOL)]

    descriptor_fields: Dict[str, str] = {}
    if force_astm_descriptor or rng.random() < 0.35:
        key = rng.choice(list(ASTM_DESCRIPTORS.keys()))
        descriptor_fields[key] = rng.choice(ASTM_DESCRIPTORS[key])

    plasticity = None
    if soil_name in {"clay", "silty clay", "clayey silt"} and rng.random() < 0.4:
        plasticity = rng.choice(["low plasticity", "high plasticity", "slightly plastic"])
    gradation = None
    if soil_name in {"sand", "sand and gravel"} and rng.random() < 0.4:
        gradation = rng.choice(["poorly graded", "well graded"])

    description = _format_description(
        fill=False,
        particle_size=particle_size,
        soil_name=soil_name,
        uscs=uscs,
        components=components,
        inclusions=inclusions,
        color=color,
        moisture=moisture,
        consistency=consistency,
        density=density,
    )

    return {
        "soil_name": soil_name,
        "particle_size_range": particle_size,
        "color": color,
        "moisture": moisture,
        "plasticity": plasticity,
        "gradation": gradation,
        "consistency": consistency,
        "density": density,
        "uscs_symbol": uscs,
        "inclusions": inclusions,
        "components": components,
        "descriptor_fields": descriptor_fields,
        "description": description,
    }


def _build_split_layers(
    rng: random.Random,
    *,
    layer_count: int,
    n_value: int,
    color_missing: bool,
    force_particle_size: Optional[bool],
    force_astm_descriptor: bool,
    recovery_inches: float,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Returns (top_level_truth, layers_jsonb).

    Top-level mirrors what `combination()` writes when a sample is split:
    the FIRST layer's representative fields at top level + descriptor_fields
    merged across all layers.
    """
    chunk = recovery_inches / layer_count
    soils = random.sample(ALL_SOILS, layer_count) if layer_count <= len(ALL_SOILS) else \
            [rng.choice(ALL_SOILS) for _ in range(layer_count)]

    layer_truths: List[Dict[str, Any]] = []
    for i, sname in enumerate(soils):
        # Within a split, share color + moisture across layers (mirrors the
        # bidirectional-inheritance behaviour of parse_split_layers).
        if i == 0:
            shared_color = None if color_missing else rng.choice(COLORS)
            shared_moisture = rng.choice(MOISTURES)
        single = _build_single_layer(
            rng,
            soil_name=sname,
            n_value=n_value,
            color_missing=color_missing,
            force_particle_size=force_particle_size,
            force_astm_descriptor=force_astm_descriptor,
        )
        single["color"] = shared_color
        single["moisture"] = shared_moisture
        single["depth_start"] = round(i * chunk, 1)
        single["depth_end"] = round((i + 1) * chunk, 1)
        # Re-format description with shared color/moisture applied.
        single["description"] = _format_description(
            fill=False,
            particle_size=single["particle_size_range"],
            soil_name=single["soil_name"],
            uscs=single["uscs_symbol"],
            components=single["components"],
            inclusions=single["inclusions"],
            color=single["color"],
            moisture=single["moisture"],
            consistency=single["consistency"],
            density=single["density"],
        )
        layer_truths.append(single)

    # Top-level: first layer + descriptor_fields merged across all layers.
    merged_descriptors: Dict[str, str] = {}
    for lf in layer_truths:
        for k, v in (lf.get("descriptor_fields") or {}).items():
            merged_descriptors.setdefault(k, v)

    first = layer_truths[0]
    top_level = {
        "soil_name": first["soil_name"],
        "particle_size_range": first["particle_size_range"],
        "color": first["color"],
        "moisture": first["moisture"],
        "plasticity": first["plasticity"],
        "gradation": first["gradation"],
        "consistency": first["consistency"],
        "density": first["density"],
        "uscs_symbol": first["uscs_symbol"],
        "inclusions": first["inclusions"],
        "components": first["components"],
        "descriptor_fields": merged_descriptors,
        "description": " / ".join(lf["description"] for lf in layer_truths),
    }

    layers_jsonb = [
        {
            "soil_name": lf["soil_name"],
            "particle_size_range": lf["particle_size_range"],
            "uscs_symbol": lf["uscs_symbol"],
            "color": lf["color"],
            "moisture": lf["moisture"],
            "plasticity": lf["plasticity"],
            "gradation": lf["gradation"],
            "consistency": lf["consistency"],
            "fill": False,
            "inclusions": lf["inclusions"],
            "components": lf["components"],
            "descriptor_fields": lf["descriptor_fields"],
            "depth_start": lf["depth_start"],
            "depth_end": lf["depth_end"],
            "description": lf["description"],
        }
        for lf in layer_truths
    ]
    return top_level, layers_jsonb
